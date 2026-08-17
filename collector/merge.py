#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH 万市枢纽 —— 合并脚本（人工审核后执行）

人工审核 data/candidates.json：
  - 删除不需要的条目（整块删除）
  - 修正字段（name/description/categories/tags/usage_tip/verification 等）
  - 需要排除但想留档的条目加 "removed": true

然后运行：python collector/merge.py
  - 新条目追加进 docs/marketplaces.json
  - 与已有条目 id 相同 → 更新动态字段（保留人工字段：verification/maintainer/first_added 等）
  - 自动重算 summary 并同步 docs/summary.json
"""

import json
import os
import shutil
import sys
import traceback
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

SCHEMA_VERSION = "2.5.0"
# 合并时保留的「人工字段」——候选采集值不覆盖它们
KEEP_FIELDS = ["maintainer", "first_added", "usage_tip"]

# 验证等级 → tags 标签（verification 已废弃，等级由 tags 表达）
LEVEL_TAGS = {
    "official": "官方",
    "community_approved": "社区验证",
    "auto_scan": "自动收录",
}


def sync_level_tags(markets):
    """验证等级并入 tags 并移除废弃的 verification 字段。

    - 旧数据若仍带 verification.level → 补对应标签（去重）
    - 无 verification 且 tags 不含任何等级标签 → 补「自动收录」（候选默认语义）
    - 最后删除 verification 字段
    """
    for m in markets:
        ver = m.get("verification")
        tag = LEVEL_TAGS.get((ver or {}).get("level")) if isinstance(ver, dict) else None
        tags = m.get("tags")
        if not isinstance(tags, list):
            tags = []
            m["tags"] = tags
        has_level_tag = any(t in tags for t in LEVEL_TAGS.values())
        if tag and tag not in tags:
            tags.append(tag)
        elif not tag and not has_level_tag:
            tags.append("自动收录")
        m.pop("verification", None)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def recompute_summary(markets):
    total = len(markets)
    by_category = {}
    active = inactive = 0
    stars = []
    item_counts = []
    most_active_id = None
    most_active_stars = -1
    for m in markets:
        for c in (m.get("categories") or []):
            by_category[c] = by_category.get(c, 0) + 1
        st = m.get("status")
        if st == "active":
            active += 1
        elif st == "inactive":
            inactive += 1
        s = (m.get("popularity") or {}).get("github_stars")
        if s is not None:
            stars.append(s)
            if st == "active" and s > most_active_stars:
                most_active_stars = s
                most_active_id = m.get("id")
        ic = m.get("item_count")
        if isinstance(ic, int):
            item_counts.append(ic)
    total_stars = sum(stars) if len(stars) == total else None
    return {
        "total_markets": total,
        "by_category": by_category,
        "total_github_stars": total_stars,
        "total_item_count": sum(item_counts) if len(item_counts) == total else None,
        "active_count": active,
        "inactive_count": inactive,
        "most_active": most_active_id,
        "last_check": now_iso(),
    }


def main():
    candidates = load(config.CANDIDATES_FILE)
    if not candidates or "markets" not in candidates:
        print("[error] 未找到候选文件 %s，请先运行 python collector/collect.py" % config.CANDIDATES_FILE)
        return 1

    doc = load(config.MARKETPLACES_FILE)
    if not doc:
        print("[error] 未找到正式数据 %s" % config.MARKETPLACES_FILE)
        return 1

    markets = doc.get("markets", [])
    added = updated = skipped = 0

    for cand in candidates.get("markets", []):
        if cand.get("removed"):
            skipped += 1
            # 候选标记 removed：跳过合并；若正式数据已有该 id，仅提示保留
            if any(m.get("id") == cand.get("id") for m in markets):
                print("[keep] %s：候选已标记 removed，正式数据中的条目保留（如需删除请在管理台数据页操作）" % cand.get("id"))
            continue
        existing = next((m for m in markets if m.get("id") == cand.get("id")), None)
        if existing:
            merged = dict(existing)
            for k, v in cand.items():
                merged[k] = v
            for k in KEEP_FIELDS:  # 保留已有的人工字段
                if k in existing:
                    merged[k] = existing[k]
            markets[markets.index(existing)] = merged
            updated += 1
            print("[update] %s" % cand.get("id"))
        else:
            markets.append(cand)
            added += 1
            print("[add] %s" % cand.get("id"))

    # id 唯一性：重复 id 追加后缀
    seen = {}
    for m in markets:
        i = m.get("id")
        if i in seen:
            n = 2
            while ("%s-%d" % (i, n)) in seen:
                n += 1
            m["id"] = "%s-%d" % (i, n)
            seen[m["id"]] = True
            print("[rename] 重复 id → %s" % m["id"])
        else:
            seen[i] = True

    summary = recompute_summary(markets)
    sync_level_tags(markets)  # 验证等级并入 tags（去重）

    # 写回前自动备份（误操作可恢复）
    try:
        shutil.copyfile(config.MARKETPLACES_FILE, config.MARKETPLACES_FILE + ".bak")
        print("[backup] 已备份旧数据 → %s.bak" % config.MARKETPLACES_FILE)
    except OSError as e:
        print("[warn] 备份失败（继续执行）：%s" % e)

    doc["markets"] = markets
    doc["summary"] = summary
    doc["file_meta"] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "valid_until": None,
    }
    with open(config.MARKETPLACES_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    summary_doc = {
        "file_meta": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now_iso(),
            "valid_until": None,
        },
        "summary": summary,
    }
    with open(config.SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary_doc, f, ensure_ascii=False, indent=2)

    print("")
    print("合并完成：新增 %d / 更新 %d / 跳过 %d" % (added, updated, skipped))
    print("市场总数：%d" % summary["total_markets"])
    print("分类分布：%s" % json.dumps(summary["by_category"], ensure_ascii=False))
    if summary.get("total_github_stars") is not None:
        print("生态总星：%d" % summary["total_github_stars"])
    if summary.get("total_item_count") is not None:
        print("生态条目：%d" % summary["total_item_count"])
    print("已写回：%s" % config.MARKETPLACES_FILE)
    print("已同步：%s" % config.SUMMARY_FILE)
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
