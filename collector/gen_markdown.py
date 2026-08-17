#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH 万市枢纽 —— 生成人类可读市场目录 MARKETS.md

读 docs/marketplaces.json，按主分类分组渲染为 Markdown（仿效 awesome-list）：
每条目格式 `- [名称](链接) — 描述`，链接可点击。

用法：
    python collector/gen_markdown.py              # 生成根目录 MARKETS.md
    python collector/gen_markdown.py --out PATH   # 指定输出路径
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MARKETS_FILE = os.path.join(ROOT, "docs", "marketplaces.json")
DEFAULT_OUT = os.path.join(ROOT, "MARKETS.md")

# 分类展示顺序与标题（与面板 CATEGORY_META 语义一致）
CATEGORY_META = [
    ("marketplace", "🏪 插件市场"),
    ("website", "🌐 插件市场网站"),
    ("library", "📚 精选库"),
    ("plugin", "🔌 插件（发现类）"),
]


def entry_line(m):
    """单条目录：- [名称](链接) — 描述"""
    name = m.get("name") or ""
    home = m.get("homepage") or ""
    if not home:
        src = m.get("data_source") or {}
        if src.get("type") == "github_repo" and src.get("identifier"):
            home = "https://github.com/" + src["identifier"]
    desc = (m.get("description") or "").strip()
    line = "- [%s](%s)" % (name, home or "")
    if desc:
        line += " — " + desc
    return line


def render(doc):
    markets = doc.get("markets", [])
    meta = doc.get("file_meta") or {}
    generated = str(meta.get("generated_at") or "")[:10] or "未知"

    groups = {key: [] for key, _ in CATEGORY_META}
    for m in markets:
        cats = m.get("categories") or []
        key = cats[0] if (cats and cats[0] in groups) else "marketplace"
        groups[key].append(m)

    lines = ["# DSH 万市枢纽 · 市场目录", ""]
    lines.append("> 自动生成于 %s · 共 %d 个市场 · 数据源 [marketplaces.json](docs/marketplaces.json)" % (generated, len(markets)))
    lines.append("")
    for key, title in CATEGORY_META:
        group = groups[key]
        lines.append("## %s（%d）" % (title, len(group)))
        lines.append("")
        lines.extend(entry_line(m) for m in group)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description="生成人类可读市场目录 MARKETS.md")
    ap.add_argument("--out", metavar="FILE", default=DEFAULT_OUT, help="输出路径（默认仓库根 MARKETS.md）")
    args = ap.parse_args()

    if not os.path.exists(MARKETS_FILE):
        print("[error] 数据文件缺失：%s" % MARKETS_FILE)
        return 0
    with open(MARKETS_FILE, encoding="utf-8") as f:
        doc = json.load(f)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(render(doc))
    n = len(doc.get("markets", []))
    print("[ok] 市场目录已生成：%s（%d 个市场）" % (args.out, n))
    return n


if __name__ == "__main__":
    sys.exit(main())
