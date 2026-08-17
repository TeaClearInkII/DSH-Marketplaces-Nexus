#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH 万市枢纽 —— AI 数据提取模块

拉取条目的 README / 网页文本，调用 DeepSeek 提取结构化信息
（条目总数 item_count、中文简介、分类建议、标签、使用建议）。

设计原则：
  - 提取结果默认写入条目 ai_hint（AI 参考），不覆盖人工字段
  - 加 --apply 才应用提取字段（description_zh/categories/tags/usage_tip/item_count）
  - 拉取文本截断至 MAX_CHARS，控制 token 成本

用法：
    python collector/ai_extract.py --all                  # 全部条目（写 ai_hint）
    python collector/ai_extract.py --all --apply          # 并应用字段
    python collector/ai_extract.py --id dsh-suite         # 单个条目
    python collector/ai_extract.py --url https://xxx      # 任意 URL 分析（仅打印）
    python collector/ai_extract.py --id dsh-suite --apply # 单条应用
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

MAX_CHARS = config.AI_INPUT_CHARS   # 送入 AI 的文本上限（字符，控制成本）
UA = "dsh-marketplaces-nexus-ai/0.1"

AI_SYSTEM = """你是 DSH（DeepSeek Harness）插件生态的数据提取助手。
输入一段文本（仓库 README 或网站页面内容）。请输出严格 JSON（不要多余文字）：
{
  "item_count": 整数或 null,
  "count_note": "条目总数的依据说明（如：README 统计约 280 条 / 页面显示 4093 个插件 / 未找到总数）",
  "description_zh": "中文简介（20-60 字，从文本提炼）",
  "categories": ["plugin" | "marketplace" | "website" | "library"],
  "tags": ["标签1", "标签2"],
  "usage_tip": "一句话使用建议"
}
规则：
- 文本中找不到可靠条目总数时 item_count 必须为 null，并在 count_note 说明。
- 数字要保守：写"280+"这类约数时取下限（280）。
- 不确定的分类返回空数组。"""


def http_get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError("HTTP %d: %s" % (e.code, body)) from e


def gh_headers():
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = "Bearer " + config.GITHUB_TOKEN
    return headers


def fetch_readme_text(identifier):
    """拉取 GitHub 仓库 README 纯文本。"""
    url = "https://api.github.com/repos/" + urllib.parse.quote(identifier, safe="/") + "/readme"
    try:
        data = json.loads(http_get(url, gh_headers()))
        if data.get("encoding") == "base64" and data.get("content"):
            text = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            # 去掉 markdown 链接语法，保留文字
            text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
            return text
    except Exception as e:
        print("[warn] README 拉取失败 %s：%s" % (identifier, e))
    return None


def fetch_web_text(url):
    """拉取网页并转纯文本。"""
    html = http_get(url)
    html = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text


def ai_extract(text, meta, system=None):
    """调用 DeepSeek 提取结构化 JSON。返回 (result, err, usage)；usage 含 token 消耗。"""
    if not config.AI_API_KEY:
        return None, "未配置 DEEPSEEK_API_KEY（.env 或环境变量）", None
    payload = {
        "model": config.AI_MODEL,
        "messages": [
            {"role": "system", "content": system or AI_SYSTEM},
            {"role": "user", "content": "条目：%s\n%s\n\n文本（截断 %d 字符）：\n%s" % (
                json.dumps(meta, ensure_ascii=False), "", MAX_CHARS, text[:MAX_CHARS])},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": config.AI_MAX_TOKENS,
    }
    try:
        req = urllib.request.Request(
            config.AI_BASE_URL.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + config.AI_API_KEY},
        )
        with urllib.request.urlopen(req, timeout=config.AI_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        # 网络/SSL/限流等一律转为可读错误，不向外抛
        return None, "AI 调用失败（%s）：%s" % (config.AI_BASE_URL, e), None
    usage = body.get("usage") or {}
    try:
        content = body["choices"][0]["message"]["content"]
        return json.loads(content), None, usage
    except (KeyError, IndexError, ValueError) as e:
        return None, "AI 返回格式异常：%s" % e, usage


def report_cost(usage, total_cost=None):
    """打印本次 AI 调用消耗（token 与估算成本，价格仅供参考）。
    total_cost：本次运行累计成本（元），非 None 时附带显示。"""
    if not usage:
        return
    pt = usage.get("prompt_tokens") or 0
    ct = usage.get("completion_tokens") or 0
    cost = pt / 1e6 * 0.5 + ct / 1e6 * 2.0   # deepseek-chat：输入 ¥0.5/M，输出 ¥2/M（估算）
    if total_cost is not None:
        print("[ai-cost] 输入 %d / 输出 %d / 合计 %d ≈ ¥%.4f（本次运行累计 ≈ ¥%.4f）" % (pt, ct, pt + ct, cost, total_cost))
    else:
        print("[ai-cost] 输入 %d token / 输出 %d token / 合计 %d ≈ ¥%.4f" % (pt, ct, pt + ct, cost))


def source_text_for(market):
    """按条目数据源取文本：github_repo → README；website → 页面。"""
    src = market.get("data_source") or {}
    if src.get("type") == "github_repo" and src.get("identifier"):
        text = fetch_readme_text(src["identifier"])
        if text:
            return text, "readme:" + src["identifier"]
    url = market.get("homepage")
    if url:
        try:
            text = fetch_web_text(url)
            if len(text) > 200:
                return text, "web:" + url
        except Exception as e:
            print("[warn] 网页拉取失败 %s：%s" % (url, e))
    return None, None


def process_market(market, apply=False):
    """处理单个条目。返回 (ok, usage)；usage 为本次 AI 调用消耗（失败时为 None）。"""
    mid = market.get("id")
    text, source = source_text_for(market)
    if not text:
        print("[skip] %s：无可用文本（README/网页均失败）" % mid)
        return False, None
    meta = {"id": mid, "name": market.get("name"), "homepage": market.get("homepage")}
    result, err, usage = ai_extract(text, meta)
    if err:
        print("[warn] %s AI 调用失败：%s" % (mid, err))
        return False, None
    report_cost(usage)
    hint = market.get("ai_hint")
    if not isinstance(hint, dict):
        hint = {"note": hint} if hint else {}
    hint["ai_extract"] = {"source": source, "result": result}
    market["ai_hint"] = hint
    print("[ai] %s：item_count=%s（%s）" % (mid, result.get("item_count"), result.get("count_note", "")))
    if apply:
        if result.get("item_count") is not None:
            market["item_count"] = result["item_count"]
            market["item_count_delta"] = None
        if result.get("description_zh"):
            market["description"] = result["description_zh"]
        if result.get("categories"):
            market["categories"] = result["categories"]
        if result.get("tags"):
            market["tags"] = result["tags"]
        if result.get("usage_tip"):
            market["usage_tip"] = result["usage_tip"]
        print("[apply] %s：字段已应用" % mid)
    time.sleep(0.5)
    return True, usage


def main():
    ap = argparse.ArgumentParser(description="AI 数据提取（README/网页 → 结构化字段）")
    ap.add_argument("--all", action="store_true", help="处理全部条目")
    ap.add_argument("--id", metavar="ID", help="处理单个条目 id")
    ap.add_argument("--url", metavar="URL", help="直接分析任意 URL（仅打印）")
    ap.add_argument("--apply", action="store_true", help="应用提取字段（默认仅写入 ai_hint）")
    ap.add_argument("--out", metavar="FILE", default=None, help="写入目标文件（默认正式数据；管理台传临时文件）")
    ap.add_argument("--no-wait", action="store_true", help="运行结束不等待回车（自动化场景）")
    args = ap.parse_args()

    if args.url:
        text = fetch_web_text(args.url)
        result, err, usage = ai_extract(text, {"url": args.url})
        if err:
            print("AI 调用失败：%s" % err)
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            report_cost(usage)
        return

    target = args.out or config.MARKETPLACES_FILE
    doc = json.load(open(target, encoding="utf-8"))
    markets = doc.get("markets", [])
    if args.id:
        markets = [m for m in markets if m.get("id") == args.id]
        if not markets:
            print("[error] 未找到条目：%s" % args.id)
            return
    if not args.id and not args.all:
        print("请指定 --all 或 --id（或 --url 直接分析）")
        return

    done = 0
    for m in markets:
        ok, _usage = process_market(m, args.apply)
        if ok:
            done += 1

    if done:
        with open(target, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print("")
        print("完成：处理 %d 条。结果写入 ai_hint%s（目标：%s）" % (done, "，字段已应用" if args.apply else "，加 --apply 可应用字段", target))
        if args.out:
            print("提示：在管理台「数据管理」确认提交后生效。")


if __name__ == "__main__":
    main()
