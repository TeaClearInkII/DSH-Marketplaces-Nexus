#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH 万市枢纽 —— 更新 README 市场目录（占位符拼接）

读 docs/marketplaces.json，按主分类分组渲染为 Markdown 片段，
替换 README.md 中 <!-- MARKETS:START --> / <!-- MARKETS:END --> 之间的内容，
其余手工内容原样保留（打开仓库首页即可见完整市场目录）。

用法：
    python collector/gen_markdown.py              # 更新 README.md 目录区
    python collector/gen_markdown.py --out FILE   # 输出独立完整 md 文件（备用）
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MARKETS_FILE = os.path.join(ROOT, "docs", "marketplaces.json")
README_PATH = os.path.join(ROOT, "README.md")
MARK_START = "<!-- MARKETS:START -->"
MARK_END = "<!-- MARKETS:END -->"

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


def group_markets(markets):
    groups = {key: [] for key, _ in CATEGORY_META}
    for m in markets:
        cats = m.get("categories") or []
        key = cats[0] if (cats and cats[0] in groups) else "marketplace"
        groups[key].append(m)
    return groups


def render_section(doc):
    """README 目录区片段（占位符之间）"""
    markets = doc.get("markets", [])
    meta = doc.get("file_meta") or {}
    generated = str(meta.get("generated_at") or "")[:10] or "未知"
    groups = group_markets(markets)
    lines = ["> 自动生成于 %s · 共 %d 个市场 · 数据源 [marketplaces.json](docs/marketplaces.json)" % (generated, len(markets)), ""]
    for key, title in CATEGORY_META:
        group = groups[key]
        lines.append("### %s（%d）" % (title, len(group)))
        lines.append("")
        lines.extend(entry_line(m) for m in group)
        lines.append("")
    return "\n".join(lines)


def render_full(doc):
    """独立完整 md 文件（--out 备用模式）"""
    markets = doc.get("markets", [])
    meta = doc.get("file_meta") or {}
    generated = str(meta.get("generated_at") or "")[:10] or "未知"
    lines = ["# DSH 万市枢纽 · 市场目录", "", "> 自动生成于 %s · 共 %d 个市场 · 数据源 [marketplaces.json](docs/marketplaces.json)" % (generated, len(markets)), ""]
    groups = group_markets(markets)
    for key, title in CATEGORY_META:
        group = groups[key]
        lines.append("## %s（%d）" % (title, len(group)))
        lines.append("")
        lines.extend(entry_line(m) for m in group)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def update_readme(doc, readme_path):
    """替换 README 占位符区间的目录内容（幂等）。"""
    with open(readme_path, encoding="utf-8") as f:
        text = f.read()
    if MARK_START not in text or MARK_END not in text:
        raise RuntimeError(
            "README.md 缺少占位符 %s / %s，请先在 README 中手动插入该区域" % (MARK_START, MARK_END))
    i0 = text.index(MARK_START) + len(MARK_START)
    i1 = text.index(MARK_END)
    new_text = text[:i0] + "\n" + render_section(doc) + text[i1:]
    if new_text == text:
        return False
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_text)
    return True


def main():
    ap = argparse.ArgumentParser(description="更新 README 市场目录（占位符拼接）或输出独立 md")
    ap.add_argument("--out", metavar="FILE", default=None, help="输出独立完整 md 文件（默认更新 README.md）")
    args = ap.parse_args()

    if not os.path.exists(MARKETS_FILE):
        print("[error] 数据文件缺失：%s" % MARKETS_FILE)
        return 0
    with open(MARKETS_FILE, encoding="utf-8") as f:
        doc = json.load(f)
    n = len(doc.get("markets", []))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(render_full(doc))
        print("[ok] 市场目录已生成：%s（%d 个市场）" % (args.out, n))
        return n

    try:
        changed = update_readme(doc, README_PATH)
    except RuntimeError as e:
        print("[error] %s" % e)
        return 0
    if changed:
        print("[ok] README 市场目录已更新（%d 个市场）" % n)
    else:
        print("[ok] README 市场目录无变化（%d 个市场）" % n)
    return n


if __name__ == "__main__":
    sys.exit(main())
