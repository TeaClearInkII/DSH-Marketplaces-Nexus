#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH 万市枢纽 —— 更新已有条目脚本

用 GitHub API + 生态结构化数据源，更新已收录条目的数值字段：
  - popularity.github_stars（收藏数）、stars_delta、last_plugin_update（pushed_at）
  - data_source.last_sync
  - item_count（可自动获取的源，见 ITEM_COUNT_SOURCES / README 链接计数）
  - topic:dsh-plugin 生态总量（报告参考）

并输出人工修订参考（真实 description/topics/language/README 链接数）。

用法：
    GITHUB_TOKEN=ghp_xxx python collector/update.py     # 推荐
    python collector/update.py                           # 匿名（限流慢）
"""

import base64
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
from merge import recompute_summary  # noqa: E402

UA = "dsh-marketplaces-nexus-updater/0.1"
SCHEMA_VERSION = "2.5.0"

# item_count 自动获取：data_source.identifier（owner/name 全名，稳定标识）→ 数据源 URL 列表
# （依次探测，取第一个成功；旧实现用迁移前的 kebab-case id 作 key，迁移后失效，勿回退）
ITEM_COUNT_SOURCES = {
    "awesome-dsh-plugin/awesome-dsh-plugin": [config.AWESOME_JSON_URL],
    "dsh-market/dsh-market": [config.AWESOME_JSON_URL],  # 同一精选库数据源
    "vvlife/whalehub-dsh": [
        "https://vvlife.github.io/whalehub-dsh/data/plugins.json",
        "https://vvlife.github.io/whalehub-dsh/plugins.json",
        "https://vvlife.github.io/whalehub-dsh/data.json",
    ],
}

# README 链接计数适用类型（估算条目数）
README_COUNT_TYPES = ["library", "website"]


def http_get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:400]
        msg = "HTTP %d: %s" % (e.code, body)
        limit = e.headers.get("X-RateLimit-Remaining")
        if limit is not None:
            msg += " [rate-limit-remaining=%s]" % limit
        raise RuntimeError(msg) from e


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gh_headers():
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = "Bearer " + config.GITHUB_TOKEN
    return headers


def github_repo(identifier):
    url = "https://api.github.com/repos/" + urllib.parse.quote(identifier, safe="/")
    return json.loads(http_get(url, gh_headers()))


def github_readme(identifier):
    url = "https://api.github.com/repos/" + urllib.parse.quote(identifier, safe="/") + "/readme"
    try:
        data = json.loads(http_get(url, gh_headers()))
        if data.get("encoding") == "base64" and data.get("content"):
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except Exception:
        return None
    return None


def github_topic_total():
    try:
        qs = urllib.parse.urlencode({"q": "topic:%s" % config.TOPIC, "per_page": 1})
        data = json.loads(http_get(config.GITHUB_SEARCH_URL + "?" + qs, gh_headers()))
        return data.get("total_count")
    except Exception:
        return None


def readme_link_count(identifier):
    """统计 README 中的 Markdown 链接列表项数量（估算收录条目数）。"""
    text = github_readme(identifier)
    if not text:
        return None
    # 匹配 `- [标题](url)` 或 `* [标题](url)` 行
    links = re.findall(r"^\s*[-*]\s+\[[^\]]+\]\([^)]+\)", text, re.MULTILINE)
    return len(links)


def set_item_count(m, n, source_note, high_confidence=False):
    """写入 item_count（自动源统一入口）。

    - 手动值（无 item_count_estimate 标记、且非 ai_refine 写入的旧值）：
      仅被高可信源覆盖（结构化 JSON / 网站明确统计，high_confidence=True）；
      README 链接估算等低可信源不覆盖，返回 False
    - 自动值（估算标记值 / AI 修正（ai_refine）写入的值）：任何源均可写入，并打估算标记
    """
    if not isinstance(n, int) or n < 0:
        return False
    old = m.get("item_count")
    hint = m.get("ai_hint") or {}
    ai_refine = hint.get("ai_refine") if isinstance(hint.get("ai_refine"), dict) else {}
    ai_written = isinstance(old, int) and ai_refine.get("item_count") == old
    is_manual = isinstance(old, int) and not hint.get("item_count_estimate") and not ai_written
    if is_manual and not high_confidence:
        return False
    m["item_count"] = n
    m["item_count_delta"] = (n - old) if isinstance(old, int) else None
    m["ai_hint"] = {"item_count_estimate": source_note}
    return True


def website_item_count(url):
    """从网站 HTML 提取条数统计（如 'xxx plugins' / 'xxx 个插件'）。"""
    try:
        html = http_get(url)
    except Exception:
        return None
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    nums = []
    for pat in config.WEBSITE_STATS_PATTERNS:
        for m in re.findall(pat, text):
            s = m.replace(",", "")
            if s.isdigit():
                nums.append(int(s))
    return max(nums) if nums else None


def count_json_list(url):
    data = json.loads(http_get(url))
    items = data if isinstance(data, list) else (data.get("plugins") or data.get("items") or [])
    return len(items)


def main(out_path=None):
    """out_path：更新结果写入的目标文件（None = 正式数据文件）。

    管理台「更新数据」用临时文件（--out data/marketplaces.tmp.json），
    不直接修改原 JSON；确认提交后才替换正式文件。
    """
    target = out_path or config.MARKETPLACES_FILE
    # token 诊断信息（只显示来源与长度，不泄露 token 本体）
    if config.GITHUB_TOKEN:
        print("[info] 使用 GitHub Token（长度 %d，来源：环境变量/.env/gh CLI 自动探测）" % len(config.GITHUB_TOKEN))
    else:
        print("[warn] 未检测到 GitHub Token：匿名模式 repos API 仅 60 次/小时，")
        print("      且共享出口 IP 极易被同 IP 用户耗尽额度（403 rate limit exceeded）。")
        print("      建议在仓库根目录创建 .env 文件并写入：GITHUB_TOKEN=ghp_xxx（脚本自动读取）")

    doc = json.load(open(target, encoding="utf-8"))
    markets = doc.get("markets", [])
    report = {"generated_at": now_iso(), "updates": [], "errors": [], "manual_review": []}

    # 生态规模参考
    total = github_topic_total()
    if total is not None:
        report["ecosystem"] = {"topic": config.TOPIC, "total_repos": total}
        print("[ok] topic:%s 生态仓库总数：%d" % (config.TOPIC, total))

    for m in markets:
        mid = m.get("id")
        src = m.get("data_source") or {}
        if src.get("type") != "github_repo" or not src.get("identifier"):
            continue
        ident = src["identifier"]
        try:
            info = github_repo(ident)
        except Exception as e:
            msg = str(e)
            report["errors"].append("%s: %s" % (mid, msg))
            print("[warn] %s 拉取失败：%s" % (mid, msg))
            if "rate limit" in msg.lower():
                print("[warn] GitHub 匿名限流已耗尽（或 token 额度不足）。请配置 GITHUB_TOKEN 后重试，剩余条目已跳过。")
                break
            time.sleep(config.REQUEST_INTERVAL)
            continue

        stars = info.get("stargazers_count")
        pushed = info.get("pushed_at")
        old_stars = (m.get("popularity") or {}).get("github_stars")
        pop = m.setdefault("popularity", {})
        if stars is not None:
            pop["github_stars"] = stars
            pop["stars_delta"] = (stars - old_stars) if isinstance(old_stars, int) else None
        else:
            # 未获取到星数：保留旧值，不覆盖为 null
            pop["stars_delta"] = None
        m["last_plugin_update"] = pushed
        src["last_sync"] = now_iso()

        # 人工修订参考
        entry = {
            "id": mid,
            "github_description": (info.get("description") or "").strip(),
            "github_topics": info.get("topics") or [],
            "language": info.get("language"),
        }
        # README 链接计数（library/website 类估算条目数）
        if (m.get("categories") or []) and any(c in README_COUNT_TYPES for c in m["categories"]):
            n = readme_link_count(ident)
            entry["readme_link_count"] = n
            if n and n >= 2:
                if set_item_count(m, n, "README 链接数估算，建议人工复核"):
                    report["updates"].append({"id": mid, "item_count_estimate": n})
                    print("[ok] %s README 链接数（估算条目）：%d" % (mid, n))
                else:
                    print("[keep] %s item_count 为手动值（%s），README 估算 %d 未覆盖" % (mid, m.get("item_count"), n))
            elif n == 1:
                print("[skip] %s README 链接计数为 %d，估算不可信，跳过" % (mid, n))
        report["manual_review"].append(entry)

        changes = []
        if stars is not None:
            changes.append("stars=%d" % stars)
        if pushed:
            changes.append("pushed=%s" % pushed[:10])
        print("[ok] %s → %s" % (mid, ", ".join(changes) or "无变化"))
        time.sleep(config.REQUEST_INTERVAL)

    # item_count：结构化数据源
    for ident, urls in ITEM_COUNT_SOURCES.items():
        m = next((x for x in markets
                  if ((x.get("data_source") or {}).get("identifier") or "").lower() == ident), None)
        if not m:
            continue
        for url in urls:
            try:
                n = count_json_list(url)
                if set_item_count(m, n, "结构化数据源（%s）" % url, high_confidence=True):
                    print("[ok] %s item_count → %d（%s）" % (mid, n, url))
                    report["updates"].append({"id": mid, "item_count": n, "source": url})
                else:
                    print("[keep] %s item_count 为手动值（%s），结构化源 %d 未覆盖" % (mid, m.get("item_count"), n))
                break
            except Exception as e:
                print("[warn] %s item_count 源 %s 失败：%s" % (mid, url, e))
                time.sleep(1)

    # 网站类条目：HTML 统计提取（无 JSON 源的兜底）
    for m in markets:
        if m.get("item_count") is not None:
            continue
        src = m.get("data_source") or {}
        if src.get("type") != "website":
            continue
        base = (m.get("homepage") or "").rstrip("/")
        if not base:
            continue
        for path in config.WEBSITE_STATS_PATHS:
            n = website_item_count(base + path)
            if n:
                if set_item_count(m, n, "网站页面统计提取，建议人工复核", high_confidence=True):
                    report["updates"].append({"id": m.get("id"), "item_count": n, "source": base + path, "method": "html"})
                    print("[ok] %s item_count → %d（HTML 统计：%s）" % (m.get("id"), n, base + path))
                else:
                    print("[keep] %s item_count 为手动值（%s），HTML 统计 %d 未覆盖" % (m.get("id"), m.get("item_count"), n))
                break
            time.sleep(1)

    # 重算 summary 并写回
    doc["summary"] = recompute_summary(markets)
    doc["file_meta"] = {"schema_version": SCHEMA_VERSION, "generated_at": now_iso(), "valid_until": None}
    with open(target, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    if out_path:
        # 临时文件模式：不触碰正式数据与 summary.json
        print("")
        print("完成。数值字段已更新到临时文件：%s" % target)
        print("人工修订参考：%s" % config.REPORT_FILE)
        print("提示：在管理台「数据管理」确认提交后，临时文件才会替换正式数据。")
        return 0

    summary_doc = {"file_meta": doc["file_meta"], "summary": doc["summary"]}
    with open(config.SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary_doc, f, ensure_ascii=False, indent=2)

    with open(config.REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("")
    print("完成。数值字段已更新：%s" % config.MARKETPLACES_FILE)
    print("人工修订参考：%s" % config.REPORT_FILE)
    print("summary 已重算（total_github_stars=%s）" % doc["summary"].get("total_github_stars"))
    return 0


def wait_exit(code):
    if "--no-wait" not in sys.argv:
        try:
            input("\n运行%s（exit %d）。按回车键关闭窗口..." % ("完成" if code == 0 else "异常结束", code))
        except EOFError:
            pass
    sys.exit(code)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="更新已有条目数值")
    ap.add_argument("--out", metavar="FILE", default=None, help="写入目标文件（默认正式数据；管理台传临时文件）")
    ap.add_argument("--no-wait", action="store_true", help="运行结束不等待回车（自动化场景）")
    args = ap.parse_args()
    try:
        code = main(out_path=args.out)
    except Exception as e:
        print("[error] 运行失败：%s" % e)
        traceback.print_exc()
        code = 1
    wait_exit(code)
