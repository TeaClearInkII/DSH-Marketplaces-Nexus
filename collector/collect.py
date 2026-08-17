#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH 万市枢纽 —— 采集脚本

流程：多源采集（GitHub Search + 精选库 plugins.json）→ 关键词过滤
      → AI 初步修正（可选）→ 输出 data/candidates.json（待人工审核）

用法：
    python collector/collect.py                          # 匿名采集（限流慢）
    GITHUB_TOKEN=xxx python collector/collect.py         # 带 token 采集
    DEEPSEEK_API_KEY=xxx python collector/collect.py     # 启用 AI 初步修正
"""

import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

UA = "dsh-marketplaces-nexus-collector/0.1"
SCHEMA_VERSION = "2.5.0"


# ── 基础 HTTP ────────────────────────────────────────────────────────────────

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


# ── 数据源 1：GitHub Search API ──────────────────────────────────────────────

def github_search():
    """多轮搜索 topic:dsh-plugin 仓库（stars 高星主流 + updated 近期活跃），自动去重合并。"""
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = "Bearer " + config.GITHUB_TOKEN
    results, seen = [], set()
    per_page = 50
    for sort, limit in config.SEARCH_ROUNDS:
        pages = max(1, (limit + per_page - 1) // per_page)
        for page in range(1, pages + 1):
            try:
                qs = urllib.parse.urlencode({
                    "q": "topic:%s" % config.TOPIC,
                    "sort": sort,
                    "order": "desc",
                    "per_page": per_page,
                    "page": page,
                })
                data = json.loads(http_get(config.GITHUB_SEARCH_URL + "?" + qs, headers))
                items = data.get("items", [])
                total = data.get("total_count", 0)
                new = [it for it in items if it.get("full_name") not in seen]
                for it in new:
                    seen.add(it.get("full_name"))
                results.extend(new)
                print("[ok] GitHub 搜索（sort=%s）第 %d 页：+%d 条（新 %d，共 %d）" % (sort, page, len(items), len(new), total))
                if not items or page >= (total + per_page - 1) // per_page:
                    break
            except Exception as e:
                print("[warn] GitHub 搜索（sort=%s）第 %d 页失败：%s" % (sort, page, e))
                if "rate limit" in str(e).lower():
                    print("[warn] 搜索限流：匿名 10 次/分钟，可配置 GITHUB_TOKEN 提升至 5000/小时；后续轮次跳过")
                    return results
            time.sleep(config.REQUEST_INTERVAL)
    cap = max((n for _, n in config.SEARCH_ROUNDS), default=50)
    return results[:cap]


# ── 数据源 2：awesome 精选库 plugins.json ────────────────────────────────────

def fetch_awesome():
    """拉取精选库清单，返回 {full_name: {awesome: True, name, description}}。"""
    out = {}
    try:
        data = json.loads(http_get(config.AWESOME_JSON_URL))
        items = data if isinstance(data, list) else (data.get("plugins") or data.get("items") or [])
        for it in items:
            url = str(it.get("url") or it.get("homepage") or "")
            if "github.com/" not in url:
                continue
            parts = url.split("github.com/")[1].strip("/").split("/")
            if len(parts) >= 2:
                full = "/".join(parts[:2])
                out[full] = {
                    "awesome": True,
                    "name": str(it.get("name") or parts[1]),
                    "description": str(it.get("description") or ""),
                }
        print("[ok] 精选库 plugins.json：%d 个仓库" % len(out))
    except Exception as e:
        print("[warn] 精选库 plugins.json 抓取失败：%s" % e)
    return out


# ── 关键词过滤 ───────────────────────────────────────────────────────────────

def match_any(text, words):
    t = text.lower()
    return [w for w in words if w.lower() in t]


def filter_repos(repos):
    """分级过滤：
    - 强市场词命中（market/marketplace/hub/精选/radar 等）→ 保留，除非命中强排除词
    - 弱市场词命中（awesome/find/registry 等）→ 需无任何排除词才保留
    """
    keep, drop = [], []
    for r in repos:
        name = r.get("name", "")
        desc = r.get("description") or ""
        topics = " ".join(r.get("topics") or [])
        hay = "%s %s %s" % (name, desc, topics)
        strong = match_any(hay, config.KEYWORDS_STRONG_INC)
        weak = match_any(hay, config.KEYWORDS_WEAK_INC)
        sexc = match_any(hay, config.KEYWORDS_STRONG_EXC)
        wexc = match_any(hay, config.KEYWORDS_WEAK_EXC)
        if (strong and not sexc) or (weak and not sexc and not wexc):
            keep.append(r)
        else:
            drop.append((name, strong, weak, sexc, wexc))
    for name, strong, weak, sexc, wexc in drop:
        print("[drop] %s  强含:%s 弱含:%s 强排:%s 弱排:%s" % (name, strong, weak, sexc, wexc))
    print("[ok] 关键词过滤：保留 %d / 剔除 %d" % (len(keep), len(drop)))
    return keep


# ── 候选条目生成（market schema 子集）────────────────────────────────────────

def guess_categories(name, desc, topics):
    hay = "%s %s %s" % (name, desc, " ".join(topics))
    cats = []
    if any(k in hay.lower() for k in ["awesome", "curated", "精选", "awesome-"]):
        cats.append("library")
    if any(k in hay.lower() for k in ["hub", "market", "aggregat", "聚合", "市场"]):
        cats.append("marketplace")
    if any(k in hay.lower() for k in ["find", "discover", "search", "导航", "会话"]):
        cats.append("plugin")
    if any(k in hay.lower() for k in ["website", "web", "site", "导航站", "index"]):
        cats.append("website")
    return (cats or ["plugin"])[:2]


def to_candidate(repo, awesome_map):
    full = repo.get("full_name", "")
    owner = (full.split("/") + [""])[0] if "/" in full else ""
    name = repo.get("name", full)
    desc = repo.get("description") or ""
    topics = repo.get("topics") or []
    cats = guess_categories(name, desc, topics)
    aw = awesome_map.get(full, {})
    cand = {
        "id": name,
        "name": name,
        "description": desc,
        "icon": "https://github.com/%s.png" % owner if owner else None,
        "icon_fallback": "default-%s.svg" % (cats[0] if cats else "plugin"),
        "homepage": repo.get("html_url") or ("https://github.com/" + full),
        "categories": cats,
        "tags": topics[:5],
        "popularity": {
            "github_stars": repo.get("stargazers_count"),
            "stars_delta": None,
            "rank": None,
        },
        "item_count": None,
        "item_count_delta": None,
        "status": "active",
        "last_plugin_update": repo.get("pushed_at"),
        "data_source": {
            "type": "github_repo",
            "identifier": full,
            "last_sync": now_iso(),
        },
        "maintainer": "@" + owner if owner else "",
        "first_added": now_iso(),
        "refresh_interval": "daily",
        "usage_tip": None,
        "upstream_sources": [],
        "npm_package": None,
        "environment": None,
        "status_message": None,
        "security_note": None,
        "last_check": now_iso(),
        "ai_hint": "已在精选库中" if aw.get("awesome") else None,
    }
    return cand


# ── 已收录基线（避免重复推荐）───────────────────────────────────────────────

def load_existing():
    try:
        with open(config.MARKETPLACES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        markets = data.get("markets", [])
        ids = {m.get("id") for m in markets}
        homes = {str(m.get("homepage", "")).rstrip("/") for m in markets}
        idents = set()
        for m in markets:
            ds = m.get("data_source") or {}
            if ds.get("identifier"):
                idents.add(str(ds["identifier"]).lower())
        return ids, homes, idents
    except Exception as e:
        print("[warn] 读取已收录数据失败（按空基线继续）：%s" % e)
        return set(), set(), set()


# ── AI 初步修正（DeepSeek，OpenAI 兼容）────────────────────────────────────

AI_SYSTEM_PROMPT = """你是 DSH（DeepSeek Harness）插件生态分析助手。
输入一个候选"市场级"资源的 GitHub 仓库信息（可能不完整）。请输出严格 JSON（不要多余文字）：
{
  "name_zh": "中文名（合适时）",
  "description_zh": "中文描述（精简，若原文为中文则润色）",
  "categories": ["plugin|marketplace|website|library", ...],
  "tags": ["标签1", "标签2"],
  "usage_tip": "一句话使用建议",
  "note": "判断依据或风险提示"
}
categories 最多两个，按重要性排序。只对明显可判断的内容填字段，不确定的用 null。"""


def ai_enhance(candidate):
    url = config.AI_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": config.AI_MODEL,
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(candidate, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": config.AI_MAX_TOKENS,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + config.AI_API_KEY},
    )
    with urllib.request.urlopen(req, timeout=config.AI_TIMEOUT) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


def run_ai(candidates):
    """对候选做 AI 初筛：结果写入候选字段，原文保留在 ai_hint。"""
    n = 0
    for c in candidates:
        if n >= config.AI_MAX_CALLS:
            print("[info] 已达 AI 调用上限（%d），其余候选留给人工审核" % config.AI_MAX_CALLS)
            break
        try:
            raw = ai_enhance(c)
            fixed = json.loads(raw)
        except Exception as e:
            print("[warn] AI 修正失败 %s：%s" % (c.get("id"), e))
            continue
        n += 1
        hint = c.get("ai_hint")
        if not isinstance(hint, dict):
            hint = {"note": hint} if hint else {}
        hint["ai"] = fixed
        c["ai_hint"] = hint
        if fixed.get("name_zh"):
            c["name"] = fixed["name_zh"]
        if fixed.get("description_zh"):
            c["description"] = fixed["description_zh"]
        if fixed.get("categories"):
            c["categories"] = fixed["categories"]
        if fixed.get("tags"):
            c["tags"] = fixed["tags"]
        if fixed.get("usage_tip"):
            c["usage_tip"] = fixed["usage_tip"]
        print("[ai] %s → %s" % (c.get("id"), fixed.get("name_zh") or c.get("id")))
        time.sleep(0.3)
    return candidates


# ── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    existing_ids, existing_homes, existing_idents = load_existing()
    report = {"generated_at": now_iso(), "sources": {}, "errors": []}

    repos = []
    if config.USE_GITHUB_SEARCH:
        items = github_search()
        report["sources"]["github_search"] = len(items)
        repos.extend(items)
    awesome_map = fetch_awesome() if config.USE_AWESOME_JSON else {}
    report["sources"]["awesome"] = len(awesome_map)

    if not repos:
        print("[error] 未采集到任何仓库，退出")
        report["errors"].append("no repos collected")
        with open(config.REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return 1

    filtered = filter_repos(repos)

    candidates = []
    seen = set()
    for r in filtered:
        cand = to_candidate(r, awesome_map)
        key = cand["homepage"].rstrip("/")
        ident = (cand.get("data_source") or {}).get("identifier") or ""
        if key in existing_homes or cand["id"] in existing_ids or (ident and ident.lower() in existing_idents):
            continue
        if key in seen:
            continue
        seen.add(key)
        candidates.append(cand)

    print("[ok] 排除已收录：剩余候选 %d 条" % len(candidates))

    if config.AI_ENABLED and candidates:
        print("[ai] 开始 AI 初步修正（上限 %d 次）" % config.AI_MAX_CALLS)
        candidates = run_ai(candidates)
    elif not config.AI_ENABLED:
        print("[info] 未设置 DEEPSEEK_API_KEY，跳过 AI 修正（人工审核时补全字段）")

    out = {
        "file_meta": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now_iso(),
            "source": ["github_search", "awesome_plugins_json"],
        },
        "total_candidates": len(candidates),
        "markets": candidates,
    }
    with open(config.CANDIDATES_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    with open(config.REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("")
    print("完成。候选写入：%s" % config.CANDIDATES_FILE)
    print("人工审核：编辑该文件（增删条目、修正字段），然后运行：")
    print("    python collector/merge.py")
    print("报告：%s" % config.REPORT_FILE)
    return 0


def wait_exit(code):
    if "--no-wait" not in sys.argv:
        try:
            input("\n运行%s（exit %d）。按回车键关闭窗口..." % ("完成" if code == 0 else "异常结束", code))
        except EOFError:
            pass
    sys.exit(code)


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:
        print("[error] 运行失败：%s" % e)
        traceback.print_exc()
        code = 1
    wait_exit(code)
