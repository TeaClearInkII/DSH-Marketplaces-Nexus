#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH 万市枢纽 —— 全自动数据流水线

一键执行：发现（多源）→ AI 初筛（排除名单/pending）→ 自动收录 → AI 修正 → 数值刷新 → 报告。

命令：
    python collector/pipeline.py                  # 一键全流程
    python collector/pipeline.py menu             # 交互菜单（排除名单/待复核/changelog）
    python collector/pipeline.py push             # git 提交推送（完成无异常时）
    python collector/pipeline.py --unexclude ID   # 移除排除项

退出码：0 成功无异常（可 push）/ 1 完成但有异常 / 2 致命（缺 key、余额不足、锁占用）
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import traceback
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # collector 目录（import config）
sys.path.insert(0, ROOT)                                          # 仓库根

import config  # noqa: E402
from collector import ai_extract  # noqa: E402

EXCLUSIONS = os.path.join(config.DATA_DIR, "exclusions.json")
PENDING = os.path.join(config.DATA_DIR, "pending.json")
CHANGELOG = os.path.join(config.DATA_DIR, "changelog.jsonl")
PIPELINE_LOG = os.path.join(config.DATA_DIR, "pipeline.log")
LOCK = os.path.join(config.DATA_DIR, ".pipeline.lock")
STAGE_FOUND = os.path.join(config.DATA_DIR, "stage_found.json")    # 发现结果暂存（供单阶段执行复用）
STAGE_SCREEN = os.path.join(config.DATA_DIR, "stage_screen.json")  # 初筛 market 列表暂存
FAILURES = os.path.join(config.DATA_DIR, "failures.json")          # 失败队列（网络/AI/复核失败）
PROGRESS = os.path.join(config.DATA_DIR, "stage_progress.json")    # 阶段断点进度（续跑用）

FAILURE_STALL = 3        # 失败计数达到该值 → 暂停自动重试（避免反复撞墙）
REVIEW_COOLDOWN = 3600   # 排除项复核冷却（秒），防止误判反复横跳
REPO_OWNER = "TeaClearInkII"
REPO_NAME = "DSH-Marketplaces-Nexus"

UA = "dsh-marketplaces-nexus-pipeline/1.0"
PLUGIN_SAFETY = ["marketplace", "registry", "directory", "awesome-list", "plugin hub", "插件市场", "精选库", "导航", "market"]
AI_SCREEN_SYSTEM = (
    "你是 DSH 插件生态分类助手。判断仓库是「插件市场/市场网站/精选库」（market）、"
    "「单插件/单工具」（plugin）、还是「不确定」（maybe）。\n"
    "规则：\n"
    "- market：聚合/收录多个插件或资源（marketplace、registry、目录、精选库、导航站、网站）\n"
    "- plugin：单功能插件/工具/skill/workflow（主题、CLI 工具、单插件、桌面应用、教程等）\n"
    "- 仅凭信息无法判断 → maybe\n"
    "只输出 JSON：{\"classification\": \"market|maybe|plugin\", \"confidence\": 0.0-1.0, \"reason\": \"一句话原因\"}"
)
REFINE_SYSTEM = (
    "你是 DSH 插件市场数据修正助手。根据 README/仓库/网站信息修正条目字段，只输出有把握的修改。\n"
    "字段规则：\n"
    "- description：20-60 字中文简介，禁止出现任何数字统计\n"
    "- categories：plugin/marketplace/website/library 数组（可多值）\n"
    "- tags：3-6 个中文或英文短标签\n"
    "- usage_tip：一句话使用建议\n"
    "- item_count：整数或 null（仅 README/页面有明确统计时给整数）\n"
    "- status：active/inactive\n"
    "- npm_package：README 中明确给出的 npm 包名，否则 null\n"
    "- homepage：该仓库自己的网站；README 里只是推荐链接则 null（并说明）\n"
    "拿不准的字段留 null，并写入 manual_request 对象（键=字段名，值=原因）。\n"
    "只输出 JSON。"
)
REFINE_FIELDS = ["description", "categories", "tags", "usage_tip", "item_count", "status", "npm_package"]


# ── 本次运行 AI 成本累计 ────────────────────────────────────────────────────
COST = {"prompt": 0, "completion": 0}


def track_cost(usage):
    """累加 usage 并返回本次运行累计成本（元）。"""
    if not usage:
        return None
    COST["prompt"] += usage.get("prompt_tokens") or 0
    COST["completion"] += usage.get("completion_tokens") or 0
    return COST["prompt"] / 1e6 * 0.5 + COST["completion"] / 1e6 * 2.0


def total_cost():
    return COST["prompt"] / 1e6 * 0.5 + COST["completion"] / 1e6 * 2.0


# ── 基础工具 ────────────────────────────────────────────────────────────────

def now_iso():
    """本地时区时间（含偏移），如 2026-08-17T07:12:34+08:00。
    日志/变更记录用本地时间；数据文件的 generated_at 仍由各脚本用 UTC（标准）。"""
    dt = datetime.now().astimezone()
    off = dt.strftime("%z")
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + off[:3] + ":" + off[3:]


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, doc):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


def log(msg):
    line = "[%s] %s" % (now_iso(), msg)
    print(line)
    try:
        with open(PIPELINE_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def changelog(entry):
    entry["ts"] = now_iso()
    with open(CHANGELOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def http_get(url, headers=None, timeout=30, retries=3):
    """HTTP GET，失败自动重试；SSL 错误转为可读提示（排查代理/网络）。"""
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(2 * attempt)
    if last is not None and ("SSL" in str(last) or "EOF" in str(last)):
        raise RuntimeError("网络/SSL 连接失败（%s）。请检查：1) 网络是否可用；2) 若开着 VPN/代理请关闭，"
                           "或在 .env 设置 HTTPS_PROXY=http://127.0.0.1:端口 后重试；3) 防火墙是否拦截" % last)
    raise last


def gh_headers():
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = "Bearer " + config.GITHUB_TOKEN
    return headers


LOCK_MAX_AGE = 1800   # 锁最长持有 30 分钟（防残留）


def acquire_lock():
    """创建运行锁。旧锁若进程已死或超时则自动清除（防强杀残留）。"""
    try:
        if os.path.exists(LOCK):
            stale = False
            try:
                with open(LOCK, encoding="utf-8") as f:
                    data = json.load(f)
                age = time.time() - float(data.get("ts", 0))
                pid = data.get("pid")
                alive = True
                if pid:
                    try:
                        os.kill(pid, 0)   # Windows 上可能不支持 0 信号
                    except OSError:
                        alive = False
                    except Exception:
                        pass
                if not alive:
                    stale = True
                    log("[lock] 检测到进程已退出（pid %s），清除残留锁" % pid)
                elif age > LOCK_MAX_AGE:
                    stale = True
                    log("[lock] 锁超时（%.0f 秒），视为残留并清除" % age)
            except (ValueError, KeyError, OSError, json.JSONDecodeError):
                stale = True   # 锁文件损坏/不可读 → 残留
            if not stale:
                return False
            os.remove(LOCK)
        with open(LOCK, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "pid": os.getpid()}, f)
        return True
    except OSError:
        return False


def release_lock():
    try:
        os.remove(LOCK)
    except OSError:
        pass


def norm_identifier(ident):
    s = str(ident or "").strip().lower()
    for p in ("https://github.com/", "http://github.com/", "github.com/", "www.github.com/"):
        if s.startswith(p):
            s = s[len(p):]
    s = s.rstrip("/").split("?")[0].split("#")[0]
    return s


# ── 失败队列（防反复重试）──────────────────────────────────────────────────

def load_failures():
    return load_json(FAILURES, {}) or {}


def save_failures(doc):
    doc["updated_at"] = now_iso()
    save_json(FAILURES, doc)


def record_failure(ident, kind, reason):
    """记录失败；fail_count 达到 FAILURE_STALL 后暂停自动重试（stalled）。"""
    doc = load_failures()
    items = doc.get("items") or []
    rec = next((f for f in items if f.get("identifier") == ident), None)
    if rec:
        rec["fail_count"] = rec.get("fail_count", 0) + 1
        rec["kind"] = kind
        rec["reason"] = reason
        rec["last_fail"] = now_iso()
        if rec["fail_count"] >= FAILURE_STALL and not rec.get("stalled"):
            rec["stalled"] = True
            log("[failure] %s 连续失败 %d 次，暂停自动重试（可在菜单手动处理）" % (ident, rec["fail_count"]))
    else:
        items.append({"identifier": ident, "kind": kind, "reason": reason,
                      "fail_count": 1, "last_fail": now_iso(), "stalled": False})
    save_failures(doc)


def clear_failure(ident):
    """成功处理（分类成功/收录/排除）后移出失败队列。"""
    doc = load_failures()
    items = doc.get("items") or []
    kept = [f for f in items if f.get("identifier") != ident]
    if len(kept) != len(items):
        doc["items"] = kept
        save_failures(doc)


def is_stalled(ident):
    return any(f.get("identifier") == ident and f.get("stalled") for f in (load_failures().get("items") or []))


def next_id(markets):
    n = 0
    for m in markets:
        mid = str(m.get("id") or "")
        if mid.startswith("m-") and mid[2:].isdigit():
            n = max(n, int(mid[2:]))
    return "m-%04d" % (n + 1)


# ── 阶段0：环境检查 ─────────────────────────────────────────────────────────

def deepseek_balance():
    if not config.AI_API_KEY:
        return None, "未配置 DEEPSEEK_API_KEY"
    try:
        data = json.loads(http_get("https://api.deepseek.com/user/balance",
                                   {"Authorization": "Bearer " + config.AI_API_KEY}))
        infos = data.get("balance_infos") or []
        total = sum(float(i.get("total_balance") or 0) for i in infos)
        return total, None
    except Exception as e:
        return None, str(e)


def check_env():
    problems = []
    if not config.GITHUB_TOKEN:
        problems.append("GITHUB_TOKEN 未配置")
    if not config.AI_API_KEY:
        problems.append("DEEPSEEK_API_KEY 未配置")
    bal, err = deepseek_balance()
    if err:
        log("[warn] DeepSeek 余额查询失败：%s" % err)
    else:
        log("[env] DeepSeek 余额：¥%.2f" % (bal or 0))
        if bal is not None and bal < 0.5:
            problems.append("DeepSeek 余额不足（¥%.2f）" % bal)
    try:
        data = json.loads(http_get("https://api.github.com/rate_limit", gh_headers()))
        core = (data.get("resources") or {}).get("core") or {}
        log("[env] GitHub 限流剩余：%s / %s" % (core.get("remaining"), core.get("limit")))
        if (core.get("remaining") or 0) < 20:
            problems.append("GitHub API 剩余配额过少（%s）" % core.get("remaining"))
    except Exception as e:
        log("[warn] GitHub rate_limit 查询失败：%s" % e)
    return problems


# ── 阶段1：发现（多源）───────────────────────────────────────────────────────

def discover():
    found = {}

    def add(ident, meta):
        ident = norm_identifier(ident)
        if not ident:
            return
        old = found.get(ident) or {}
        old.update(meta)
        found[ident] = old

    # 1) GitHub 搜索
    for sort, per in config.SEARCH_ROUNDS:
        pages = max(1, (per + 49) // 50)
        for page in range(1, pages + 1):
            q = urllib.parse.urlencode({"q": "topic:%s" % config.TOPIC})
            url = "%s?%s&sort=%s&order=desc&per_page=50&page=%d" % (config.GITHUB_SEARCH_URL, q, sort, page)
            try:
                data = json.loads(http_get(url, gh_headers()))
            except Exception as e:
                log("[warn] 搜索失败 sort=%s page=%d：%s" % (sort, page, e))
                time.sleep(3)
                continue
            for r in data.get("items", []):
                add(r.get("full_name"), r)
            time.sleep(config.REQUEST_INTERVAL)
    log("[discover] GitHub 搜索：%d 个仓库" % len(found))

    # 2) awesome 精选库
    if config.USE_AWESOME_JSON:
        try:
            data = json.loads(http_get(config.AWESOME_JSON_URL))
            items = data if isinstance(data, list) else (data.get("plugins") or data.get("items") or [])
            n = 0
            for it in items:
                url = it.get("repository") or it.get("repo") or it.get("url") or it.get("homepage")
                if url and "github.com/" in str(url):
                    add(url, {"_awesome": True})
                    n += 1
            log("[discover] awesome 精选库：%d 条（合并后去重）" % n)
        except Exception as e:
            log("[warn] awesome json 拉取失败：%s" % e)

    # 3) 本仓库 Issues（ADD_MARKET 模板建议收录）
    try:
        url = "https://api.github.com/repos/%s/%s/issues?state=open&per_page=100" % (REPO_OWNER, REPO_NAME)
        issues = json.loads(http_get(url, gh_headers()))
        n = 0
        for it in issues:
            body = "%s %s" % (it.get("title") or "", it.get("body") or "")
            for u in re.findall(r"https?://github\.com/[\w\-\.]+/[\w\-\.]+", body):
                add(u, {"_issue": it.get("number")})
                n += 1
        log("[discover] Issues 建议：%d 条" % n)
    except Exception as e:
        log("[warn] Issues 拉取失败：%s" % e)

    return found


def filter_excluded(found):
    excl = load_json(EXCLUSIONS, {}) or {}
    items = excl.get("items") or []
    by_ident = {e.get("identifier"): e for e in items}
    kept = {}
    recheck = []
    for ident, meta in found.items():
        rec = by_ident.get(ident)
        if not rec:
            kept[ident] = meta
            continue
        stars = meta.get("stargazers_count") or 0
        if rec.get("stable"):
            continue
        if rec.get("stars") and stars and stars > rec["stars"] * 2:
            recheck.append((ident, meta, rec))
            log("[review] %s 星数翻倍（%s→%s），强制重新评估" % (ident, rec.get("stars"), stars))
        else:
            kept[ident] = meta  # 未稳定：本轮回候选池重新过 AI（复核计数在阶段2）
    return kept, recheck


def keyword_filter(found, existing_idents):
    result = {}
    for ident, meta in found.items():
        if ident in existing_idents:
            continue
        text = ("%s %s %s" % (ident, meta.get("full_name") or "", meta.get("description") or "")).lower()
        if any(k in text for k in config.KEYWORDS_STRONG_EXC):
            continue
        strong = any(k in text for k in config.KEYWORDS_STRONG_INC)
        weak = any(k in text for k in config.KEYWORDS_WEAK_INC)
        weak_exc = any(k in text for k in config.KEYWORDS_WEAK_EXC)
        if strong or (weak and not weak_exc):
            result[ident] = meta
    return result


def fetch_readme(ident, budget):
    if budget["used"] >= budget["max"]:
        return None
    budget["used"] += 1
    try:
        url = "https://api.github.com/repos/%s/readme" % urllib.parse.quote(ident, safe="/")
        data = json.loads(http_get(url, gh_headers()))
        if data.get("encoding") == "base64" and data.get("content"):
            import base64
            text = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    except Exception:
        return None
    return None


# ── 阶段2：AI 初筛 ──────────────────────────────────────────────────────────

def ai_screen(ident, meta, readme=None, max_chars=None):
    text = "%s %s %s" % (ident, meta.get("description") or "", readme or "")
    text = text[:(max_chars or config.AI_INPUT_CHARS)]
    result, err, usage = ai_extract.ai_extract(text, {"id": ident, "task": "classify"}, system=AI_SCREEN_SYSTEM)
    if err:
        log("[warn] %s AI 初筛失败：%s" % (ident, err))
        return "maybe", 0.0, usage
    ai_extract.report_cost(usage, track_cost(usage))
    return result.get("classification") or "maybe", float(result.get("confidence") or 0.0), usage


def screen_all(candidates, readme_budget):
    """返回 (market_list, plugin_list, maybe_list)；调用受 AI_MAX_CALLS 限流。
    失败项进失败队列（连续失败自动暂停重试）；成功项清除失败记录。"""
    market_list, plugin_list, maybe_list = [], [], []
    n = 0
    for ident, meta in candidates.items():
        if is_stalled(ident):
            log("[skip] %s 失败队列已暂停（连续失败），跳过本轮" % ident)
            continue
        if n >= config.AI_MAX_CALLS:
            log("[info] 已达 AI 调用上限（%d），其余进 pending 下轮处理" % config.AI_MAX_CALLS)
            maybe_list.append((ident, meta))
            continue
        readme = fetch_readme(ident, readme_budget)
        cls, conf, _u = ai_screen(ident, meta, readme)
        n += 1
        if _u is None:
            record_failure(ident, "ai", "AI 初筛调用失败")
            maybe_list.append((ident, meta))
            continue
        clear_failure(ident)
        if cls == "market" and conf >= 0.85:
            market_list.append((ident, meta))
            log("[screen] %s → market（%.2f）" % (ident, conf))
        elif cls == "plugin" and conf >= 0.85:
            # 脚本特征兜底：README 含市场特征则不当 plugin
            if readme and any(k in readme.lower() for k in PLUGIN_SAFETY):
                market_list.append((ident, meta))
                log("[screen] %s → plugin 但 README 含市场特征，按 market 处理（%.2f）" % (ident, conf))
            else:
                plugin_list.append((ident, meta))
                log("[screen] %s → plugin（%.2f）" % (ident, conf))
        else:
            maybe_list.append((ident, meta))
            log("[screen] %s → maybe（%.2f）" % (ident, conf))
    return market_list, plugin_list, maybe_list


def update_exclusions(plugin_list):
    excl = load_json(EXCLUSIONS, {}) or {}
    items = excl.get("items") or []
    by_ident = {e.get("identifier"): e for e in items}
    for ident, meta in plugin_list:
        rec = by_ident.get(ident)
        if rec:
            rec["review_count"] = rec.get("review_count", 0) + 1
            rec["last_reviewed_ts"] = time.time()
            if rec["review_count"] >= 3:
                rec["stable"] = True
                log("[exclude] %s 连续 %d 次判定 plugin，标记稳定不再复核" % (ident, rec["review_count"]))
        else:
            items.append({
                "identifier": ident,
                "name": meta.get("name") or ident.split("/")[-1],
                "reason": "AI 初筛 plugin（高置信）",
                "confidence": 0.9,
                "stars": meta.get("stargazers_count"),
                "review_count": 1,
                "stable": False,
            })
            changelog({"action": "exclude", "identifier": ident, "name": meta.get("name") or ident})
            log("[exclude] %s → 排除名单" % ident)
    excl["items"] = items
    excl["updated_at"] = now_iso()
    save_json(EXCLUSIONS, excl)


# ── 阶段3：自动收录 ─────────────────────────────────────────────────────────

def revive_from_screen(non_plugin):
    """AI 复核判定非 plugin 的未稳定排除项 → 移出排除名单（可再次参与收录）。"""
    excl = load_json(EXCLUSIONS, {}) or {}
    items = excl.get("items") or []
    ids = {ident for ident, _ in non_plugin}
    revived = False
    for e in items:
        if e.get("identifier") in ids and not e.get("stable"):
            e["revived"] = True
            changelog({"action": "revive", "identifier": e.get("identifier"), "reason": "AI 复核判定非 plugin"})
            log("[exclude] %s 复核后判定非 plugin，移出排除名单" % e.get("identifier"))
            revived = True
    if revived:
        excl["items"] = [e for e in items if not e.get("revived")]
        excl["updated_at"] = now_iso()
        save_json(EXCLUSIONS, excl)


def ingest(market_list):
    doc = load_json(config.MARKETPLACES_FILE)
    if not doc:
        log("[error] 正式数据文件缺失")
        return 0
    markets = doc.get("markets", [])
    existing = {norm_identifier((m.get("data_source") or {}).get("identifier")): m for m in markets}
    added = 0
    for ident, meta in market_list:
        if ident in existing:
            continue  # 已收录（同名仓库）
        entry = {
            "id": next_id(markets),
            "name": meta.get("name") or ident.split("/")[-1],
            "description": (meta.get("description") or "")[:200],
            "icon": meta.get("owner", {}).get("avatar_url") if isinstance(meta.get("owner"), dict) else None,
            "icon_fallback": None,
            "homepage": meta.get("html_url") or ("https://github.com/" + ident),
            "categories": ["marketplace"],
            "tags": ["自动收录"],
            "popularity": {
                "github_stars": meta.get("stargazers_count"),
                "stars_delta": None,
                "rank": None,
            },
            "item_count": None,
            "item_count_delta": None,
            "status": "active",
            "last_plugin_update": meta.get("pushed_at"),
            "data_source": {"type": "github_repo", "identifier": ident, "last_sync": now_iso()},
            "maintainer": "@" + ident.split("/")[0],
            "first_added": now_iso(),
            "refresh_interval": "daily",
            "usage_tip": None,
            "upstream_sources": [],
            "npm_package": None,
            "environment": None,
            "status_message": None,
            "security_note": None,
            "last_check": now_iso(),
            "ai_hint": {"pipeline": "自动收录（AI 初筛 market ≥0.85）"},
        }
        markets.append(entry)
        existing[ident] = entry
        changelog({"action": "add", "id": entry["id"], "identifier": ident, "name": entry["name"]})
        log("[add] %s → %s（%s）" % (entry["id"], entry["name"], ident))
        added += 1
    if added:
        doc["markets"] = markets
        doc["summary"] = recompute_summary(markets)
        save_json(config.MARKETPLACES_FILE, doc)
        log("[ingest] 新增 %d 条，已写入正式数据" % added)
    return added


def recompute_summary(markets):
    from collector.merge import recompute_summary as rs
    return rs(markets)


def migrate_ids():
    """首次运行：把旧 id（kebab-case）迁移为编号格式 m-0001…（写 changelog）。"""
    doc = load_json(config.MARKETPLACES_FILE)
    if not doc:
        return
    markets = doc.get("markets", [])
    if not any(not str(m.get("id") or "").startswith("m-") for m in markets):
        return
    n = 0
    for m in markets:
        if not str(m.get("id") or "").startswith("m-"):
            old = m.get("id")
            m["id"] = "m-%04d" % (n + 1)
            n += 1
            changelog({"action": "migrate_id", "old": old, "new": m["id"],
                       "identifier": (m.get("data_source") or {}).get("identifier")})
            log("[migrate] %s → %s" % (old, m["id"]))
    save_json(config.MARKETPLACES_FILE, doc)


def store_pending(maybe_list):
    pend = load_json(PENDING, {}) or {}
    items = pend.get("items") or []
    known = {p.get("identifier") for p in items}
    for ident, meta in maybe_list:
        if ident in known:
            continue
        items.append({
            "identifier": ident,
            "name": meta.get("name") or ident.split("/")[-1],
            "stars": meta.get("stargazers_count"),
            "reason": "AI 初筛 maybe 或低置信",
            "first_seen": now_iso(),
            "attempts": 0,
        })
    pend["items"] = items
    pend["updated_at"] = now_iso()
    save_json(PENDING, pend)
    log("[pending] 待复核池现有 %d 条（新加入 %d）" % (len(items), len(items) - len(known)))


def review_pending(readme_budget):
    """pending 池再次 AI 判定：market 高置信 → 收录；attempts 递增，超过 3 次移出。"""
    pend = load_json(PENDING, {}) or {}
    items = pend.get("items") or []
    doc = load_json(config.MARKETPLACES_FILE)
    markets = doc.get("markets", []) if doc else []
    existing = {norm_identifier((m.get("data_source") or {}).get("identifier")): m for m in markets}
    n = 0
    keep, to_ingest, dropped = [], [], []
    for p in items:
        ident = p.get("identifier")
        if ident in existing:
            continue
        if p.get("attempts", 0) >= 3:
            dropped.append(p)
            continue
        if is_stalled(ident):
            keep.append(p)
            continue
        if n >= config.AI_MAX_CALLS:
            keep.append(p)
            continue
        readme = fetch_readme(ident, readme_budget)
        cls, conf, _u = ai_screen(ident, {"name": p.get("name")}, readme)
        n += 1
        if _u is None:
            record_failure(ident, "ai", "pending 复核调用失败")
            keep.append(p)
            continue
        clear_failure(ident)
        if cls == "market" and conf >= 0.85:
            to_ingest.append((ident, {"name": p.get("name"), "stargazers_count": p.get("stars"),
                                     "pushed_at": None, "description": "", "html_url": "https://github.com/" + ident}))
            log("[pending] %s 复核为 market（%.2f），收录" % (ident, conf))
        else:
            p["attempts"] = p.get("attempts", 0) + 1
            keep.append(p)
    if to_ingest:
        ingest(to_ingest)
    if dropped:
        for d in dropped:
            record_failure(d.get("identifier"), "review", "pending 复核 3 次未通过")
            log("[pending] %s 复核 3 次未通过，归档到失败队列" % d.get("identifier"))
    pend["items"] = keep
    pend["updated_at"] = now_iso()
    save_json(PENDING, pend)


# ── 阶段4：AI 修正（已收录条目）─────────────────────────────────────────────

def refine_markets(limit=None, readme_budget=None):
    """全量/按刷新频率修正已收录条目：白名单字段 + 防震荡 + 数字清理 + manual_request。"""
    doc = load_json(config.MARKETPLACES_FILE)
    if not doc:
        return 0
    markets = doc.get("markets", [])
    if readme_budget is None:
        readme_budget = {"used": 0, "max": 40}
    done = 0
    for m in markets:
        if limit is not None and done >= limit:
            break
        # 有 manual_request 标记的条目：AI 已声明拿不准，跳过自动修正（等人工处理）
        hint0 = m.get("ai_hint")
        if isinstance(hint0, dict) and hint0.get("manual_request"):
            log("[refine] %s 有 manual_request 建议，跳过自动修正（待人工处理）" % m.get("id"))
            continue
        src = m.get("data_source") or {}
        ident = src.get("identifier")
        if not ident:
            continue
        readme = fetch_readme(ident, readme_budget)
        if not readme:
            continue
        # 数字清理：description 含数字 → 交由 AI 重写（提示词禁止数字）
        result, err, usage = ai_extract.ai_extract(
            readme[:config.AI_INPUT_CHARS],
            {"id": m.get("id"), "name": m.get("name"), "task": "refine"},
            system=REFINE_SYSTEM,
        )
        if err:
            log("[warn] %s AI 修正失败：%s" % (m.get("id"), err))
            continue
        ai_extract.report_cost(usage, track_cost(usage))
        hint = m.get("ai_hint")
        if not isinstance(hint, dict):
            hint = {}
        prev = (hint.get("ai_refine") or {}) if isinstance(hint.get("ai_refine"), dict) else {}
        changed_fields = []
        for field in REFINE_FIELDS:
            new_val = result.get(field)
            if new_val is None:
                continue
            if field in ("categories", "tags"):
                new_val = [x.strip() for x in new_val] if isinstance(new_val, list) else []
                if not new_val:
                    continue
            if prev.get(field) == new_val:
                continue  # 防震荡：与上次修正值相同则跳过
            if field == "item_count" and not isinstance(new_val, int):
                continue
            if field == "npm_package":
                if not npm_exists(new_val):
                    continue
            old = m.get(field)
            if old == new_val:
                continue
            m[field] = new_val
            prev[field] = new_val
            changed_fields.append(field)
            changelog({"action": "refine", "id": m.get("id"), "field": field,
                       "old": old, "new": new_val})
        manual = result.get("manual_request")
        if isinstance(manual, dict) and manual:
            hint["manual_request"] = manual
            log("[manual] %s 建议人工处理：%s" % (m.get("id"), json.dumps(manual, ensure_ascii=False)))
        if changed_fields:
            hint["ai_refine"] = prev
            m["ai_hint"] = hint
            m["last_check"] = now_iso()
            log("[refine] %s 修正字段：%s" % (m.get("id"), ", ".join(changed_fields)))
            done += 1
    if done:
        doc["markets"] = markets
        save_json(config.MARKETPLACES_FILE, doc)
    return done


def npm_exists(pkg):
    if not pkg or not isinstance(pkg, str):
        return False
    try:
        data = json.loads(http_get("https://registry.npmjs.org/%s/latest" % urllib.parse.quote(pkg), timeout=15))
        return bool(data and data.get("version"))
    except Exception:
        return False


# ── 阶段5：数值刷新（复用 update.py）────────────────────────────────────────

def refresh_values():
    from collector import update as updater
    return updater.main(out_path=config.MARKETPLACES_FILE)


# ── 阶段6：汇总报告 ─────────────────────────────────────────────────────────

def write_report(stats):
    doc = {
        "generated_at": now_iso(),
        "stats": stats,
        "exclusions_count": len((load_json(EXCLUSIONS, {}) or {}).get("items") or []),
        "pending_count": len((load_json(PENDING, {}) or {}).get("items") or []),
        "markets_count": len((load_json(config.MARKETPLACES_FILE) or {}).get("markets") or []),
    }
    save_json(config.REPORT_FILE, doc)
    log("[report] %s" % json.dumps(stats, ensure_ascii=False))


# ── 阶段函数（可单独执行）──────────────────────────────────────────────────

def compact_meta(meta):
    return {
        "name": meta.get("name"),
        "stars": meta.get("stargazers_count"),
        "pushed_at": meta.get("pushed_at"),
        "description": (meta.get("description") or "")[:300],
        "html_url": meta.get("html_url") or ("https://github.com/" + norm_identifier(meta.get("full_name") or "")),
        "owner_avatar": ((meta.get("owner") or {}).get("avatar_url")
                         if isinstance(meta.get("owner"), dict) else None),
        "full_name": meta.get("full_name"),
    }


def run_stage_discover():
    """仅发现：多源扫描 → 存 stage_found.json。"""
    found = discover()
    save_json(STAGE_FOUND, {"found": {ident: compact_meta(m) for ident, m in found.items()}, "ts": now_iso()})
    log("[stage] 发现完成：%d 个（已存 stage_found.json）" % len(found))
    return 0


def run_stage_screen():
    """仅 AI 初筛：读 stage_found → 排除名单/关键词过滤 → AI 分类 → 排除/pending/market 列表。"""
    data = load_json(STAGE_FOUND)
    if not data or not data.get("found"):
        log("[stage] 无发现结果，请先执行「仅发现」")
        return 1
    found = data.get("found") or {}
    doc = load_json(config.MARKETPLACES_FILE) or {}
    existing_idents = {norm_identifier((m.get("data_source") or {}).get("identifier")) for m in doc.get("markets", [])}
    kept, _recheck = filter_excluded(found)
    candidates = keyword_filter(kept, existing_idents)
    # 未稳定排除项强制复核（带冷却：距上次复核 < REVIEW_COOLDOWN 跳过，防误判横跳）
    excl = load_json(EXCLUSIONS, {}) or {}
    now_ts = time.time()
    for e in excl.get("items") or []:
        if e.get("stable") or e.get("review_count", 0) >= 3:
            continue
        last = e.get("last_reviewed_ts") or 0
        if now_ts - float(last) < REVIEW_COOLDOWN:
            continue
        ident = e.get("identifier")
        if ident in found and ident not in candidates:
            candidates[ident] = found[ident]
    log("[stage] 过滤后候选：%d" % len(candidates))
    readme_budget = {"used": 0, "max": 80}
    market_list, plugin_list, maybe_list = screen_all(candidates, readme_budget)
    revive_from_screen(market_list + maybe_list)
    update_exclusions(plugin_list)
    store_pending(maybe_list)
    save_json(STAGE_SCREEN, {"market": [i for i, _ in market_list], "ts": now_iso()})
    log("[stage] 初筛完成：market %d / plugin %d / maybe %d" % (len(market_list), len(plugin_list), len(maybe_list)))
    return 0


def run_stage_ingest():
    """仅自动收录：读 stage_screen.market → 入库（含 id 迁移）。"""
    data = load_json(STAGE_SCREEN)
    if not data or not data.get("market"):
        log("[stage] 无初筛 market 结果，请先执行「仅 AI 初筛」")
        return 1
    found = (load_json(STAGE_FOUND) or {}).get("found") or {}
    market_list = [(i, found.get(i) or {}) for i in data["market"]]
    migrate_ids()
    n = ingest(market_list)
    log("[stage] 收录完成：新增 %d 条" % n)
    return n


def run_stage_refine():
    """仅 AI 修正：已收录条目全量修正（白名单字段/防震荡/数字清理）。"""
    readme_budget = {"used": 0, "max": 40}
    n = refine_markets(readme_budget=readme_budget)
    log("[stage] AI 修正完成：%d 条" % n)
    return n


def run_stage_refresh():
    """仅数值刷新：stars/pushed_at/网站统计/summary。"""
    from collector import update as updater
    updater.main()   # 不传 out_path → 正式文件 + summary 正常同步
    return 0


# ── 主流程 ──────────────────────────────────────────────────────────────────

def run_pipeline():
    t0 = time.time()
    problems = check_env()
    if problems:
        for p in problems:
            log("[fatal] %s" % p)
        return 2
    if not acquire_lock():
        log("[fatal] 已有 pipeline 在运行（锁占用），跳过本轮")
        return 2
    stats = {"discovered": 0, "new_added": 0, "excluded": 0, "refined": 0, "errors": 0}
    try:
        # 断点续跑：跳过已完成阶段（异常中断后重跑从断点继续）
        progress = load_json(PROGRESS, {}) or {}
        done = set(progress.get("done") or [])
        n_refine = 0
        for name, fn in [("discover", run_stage_discover), ("screen", run_stage_screen),
                         ("ingest", run_stage_ingest), ("refine", run_stage_refine),
                         ("refresh", run_stage_refresh)]:
            if name in done:
                log("[resume] 阶段 %s 已完成，跳过" % name)
                continue
            save_json(PROGRESS, {"done": sorted(done), "ts": now_iso()})
            ret = fn()
            if name == "refine" and isinstance(ret, int):
                n_refine = ret
            done.add(name)
            save_json(PROGRESS, {"done": sorted(done), "ts": now_iso()})
        # 整轮完成：清除断点
        try:
            os.remove(PROGRESS)
        except OSError:
            pass
        found_data = load_json(STAGE_FOUND) or {}
        stats["discovered"] = len(found_data.get("found") or {})
        stats["excluded"] = len((load_json(EXCLUSIONS, {}) or {}).get("items") or [])
        stats["refined"] = n_refine
        write_report(stats)
        cost_line = "，AI 成本合计 ≈ ¥%.4f" % total_cost()
        log("[pipeline] 完成，耗时 %.1f 秒%s：%s" % (time.time() - t0, cost_line, json.dumps(stats, ensure_ascii=False)))
        # 失败通知：有失败项时醒目提示
        fails = (load_failures().get("items") or [])
        if fails:
            stalled_n = sum(1 for f in fails if f.get("stalled"))
            print("\n=== 警告：失败队列有 %d 项（其中 %d 项已暂停自动重试）===" % (len(fails), stalled_n))
            for f in fails[:10]:
                print("  %s  [%s] 失败%d次%s  %s" % (f.get("identifier"), f.get("kind"), f.get("fail_count"),
                                                   " [已暂停]" if f.get("stalled") else "", f.get("reason", "")))
            if len(fails) > 10:
                print("  …共 %d 项，详见 data/failures.json 或菜单查看" % len(fails))
        return 0
    except Exception as e:
        log("[error] pipeline 异常：%s" % e)
        traceback.print_exc()
        stats["errors"] += 1
        write_report(stats)
        return 1
    finally:
        release_lock()


# ── CLI 菜单 ────────────────────────────────────────────────────────────────

CONFIG_ITEMS = [
    ("AI_MAX_CALLS", "AI_MAX_CALLS", "每轮 AI 调用上限"),
    ("DEEPSEEK_MAX_TOKENS", "AI_MAX_TOKENS", "单次输出上限（token）"),
    ("DEEPSEEK_INPUT_CHARS", "AI_INPUT_CHARS", "单次输入上限（字符）"),
    ("DSH_SCAN_STARS", None, "星数轮扫描量"),
    ("DSH_SCAN_UPDATED", None, "更新轮扫描量"),
    ("DSH_MIN_STARS", "MIN_STARS", "最小星数过滤"),
    ("DEEPSEEK_MODEL", "AI_MODEL", "AI 模型"),
    ("DSH_USE_GITHUB_SEARCH", "USE_GITHUB_SEARCH", "GitHub 搜索开关（1/0）"),
    ("DSH_USE_AWESOME", "USE_AWESOME_JSON", "awesome 精选库开关（1/0）"),
]


def mask_secret(v):
    v = str(v or "")
    if len(v) >= 8:
        return v[:4] + "***" + v[-4:]
    return "***" if v else ""


def display_config_value(key, attr):
    if attr:
        return str(getattr(config, attr, ""))
    if key == "DSH_SCAN_STARS":
        return str(next((n for s, n in config.SEARCH_ROUNDS if s == "stars"), ""))
    if key == "DSH_SCAN_UPDATED":
        return str(next((n for s, n in config.SEARCH_ROUNDS if s == "updated"), ""))
    return ""


def cmd_config():
    """配置查看/修改子菜单：输入 编号=新值 修改（写入 .env，下次运行生效）。"""
    while True:
        print("\n===== 配置（.env，下次运行生效）=====")
        for i, (key, attr, label) in enumerate(CONFIG_ITEMS, 1):
            print("  %d. %s = %s   （%s）" % (i, key, display_config_value(key, attr), label))
        print("  T. GITHUB_TOKEN：%s（输入 T=新值 设置）" % (
            "已配置（掩码 %s）" % mask_secret(config.GITHUB_TOKEN) if config.GITHUB_TOKEN else "未配置"))
        print("  K. DEEPSEEK_API_KEY：%s（输入 K=新值 设置）" % (
            "已配置（掩码 %s）" % mask_secret(config.AI_API_KEY) if config.AI_API_KEY else "未配置"))
        print("  [回车] 返回上一级")
        try:
            line = input("输入（如 1=30 或 T=ghp_xxx）：").strip()
        except EOFError:
            break
        if not line:
            break
        if "=" not in line:
            print("格式：编号=新值")
            continue
        idx, _, val = line.partition("=")
        idx, val = idx.strip().upper(), val.strip()
        if idx == "T":
            apply_set_args(["GITHUB_TOKEN=" + val])
        elif idx == "K":
            apply_set_args(["DEEPSEEK_API_KEY=" + val])
        elif idx.isdigit() and 1 <= int(idx) <= len(CONFIG_ITEMS):
            key = CONFIG_ITEMS[int(idx) - 1][0]
            apply_set_args([key + "=" + val])
        else:
            print("无效编号")
        input("（按回车继续）")

def cmd_menu():
    while True:
        print("\n===== DSH 万市枢纽 · pipeline 菜单 =====")
        print("[1] 执行全流程（发现→初筛→收录→修正→刷新）")
        print("[2] 仅发现（多源扫描）")
        print("[3] 仅 AI 初筛（排除名单/待复核）")
        print("[4] 仅自动收录")
        print("[5] 仅 AI 修正（已收录条目）")
        print("[6] 仅数值刷新")
        print("[7] 浏览排除名单")
        print("[8] 移除排除项")
        print("[9] 添加排除项")
        print("[10] 查看待复核池")
        print("[11] changelog 摘要（最近 20 条）")
        print("[12] git 提交推送")
        print("[13] 查看/修改配置（.env）")
        print("[14] 查看最近报告")
        print("[15] 查看/清理失败队列")
        print("[16] 清除断点进度（从头跑全流程）")
        print("[17] 查看 manual_request（AI 建议人工处理项）")
        print("[0] 退出")
        try:
            choice = input("选择：").strip()
        except EOFError:
            break
        if choice == "1":
            code = run_pipeline()
            print("（pipeline 退出码：%d）" % code)
        elif choice == "2":
            print("（仅发现：退出码 %d）" % run_stage_discover())
        elif choice == "3":
            print("（仅 AI 初筛：退出码 %d）" % run_stage_screen())
        elif choice == "4":
            print("（仅自动收录：新增 %d 条）" % run_stage_ingest())
        elif choice == "5":
            print("（仅 AI 修正：%d 条）" % run_stage_refine())
        elif choice == "6":
            print("（仅数值刷新：退出码 %d）" % run_stage_refresh())
        elif choice == "7":
            excl = (load_json(EXCLUSIONS, {}) or {}).get("items") or []
            if not excl:
                print("（空）")
            for e in excl:
                print("  %s  %s  ★%s  复核%d%s  %s" % (
                    e.get("identifier"), e.get("name"), e.get("stars") or "?",
                    e.get("review_count", 0), " [稳定]" if e.get("stable") else "", e.get("reason", "")))
        elif choice == "8":
            ident = input("输入排除项 identifier（owner/name）：").strip()
            excl = load_json(EXCLUSIONS, {}) or {}
            items = [e for e in excl.get("items") or [] if e.get("identifier") != norm_identifier(ident)]
            excl["items"] = items
            excl["updated_at"] = now_iso()
            save_json(EXCLUSIONS, excl)
            changelog({"action": "unexclude", "identifier": norm_identifier(ident)})
            print("已移除。")
        elif choice == "9":
            ident = input("输入 identifier（owner/name）：").strip()
            reason = input("排除原因：").strip()
            excl = load_json(EXCLUSIONS, {}) or {}
            items = excl.get("items") or []
            items.append({"identifier": norm_identifier(ident), "name": ident.split("/")[-1],
                          "reason": reason or "手动添加", "review_count": 3, "stable": True})
            excl["items"] = items
            excl["updated_at"] = now_iso()
            save_json(EXCLUSIONS, excl)
            changelog({"action": "exclude", "identifier": norm_identifier(ident), "reason": reason or "手动添加"})
            print("已添加（直接标记稳定）。")
        elif choice == "10":
            pend = (load_json(PENDING, {}) or {}).get("items") or []
            if not pend:
                print("（空）")
            for p in pend:
                print("  %s  %s  ★%s  尝试%d  %s" % (p.get("identifier"), p.get("name"),
                                                     p.get("stars") or "?", p.get("attempts", 0), p.get("reason", "")))
        elif choice == "11":
            try:
                with open(CHANGELOG, encoding="utf-8") as f:
                    lines = [json.loads(l) for l in f if l.strip()]
                for e in lines[-20:]:
                    print("  %s %s %s %s" % (e.get("ts", "")[11:19], e.get("action"), e.get("id") or e.get("identifier"), e.get("field", "")))
            except OSError:
                print("（无 changelog）")
        elif choice == "12":
            cmd_push()
        elif choice == "13":
            cmd_config()
        elif choice == "14":
            report = load_json(config.REPORT_FILE)
            if not report:
                print("（暂无报告，执行全流程后生成）")
            else:
                print("生成时间：%s" % report.get("generated_at"))
                print("统计：%s" % json.dumps(report.get("stats") or {}, ensure_ascii=False))
                print("市场数：%s  排除名单：%s  待复核：%s" % (
                    report.get("markets_count"), report.get("exclusions_count"), report.get("pending_count")))
        elif choice == "15":
            fails = (load_failures().get("items") or [])
            if not fails:
                print("（失败队列为空）")
            else:
                for i, f in enumerate(fails, 1):
                    print("  %d. %s  [%s] 失败%d次%s  %s" % (
                        i, f.get("identifier"), f.get("kind"), f.get("fail_count"),
                        " [已暂停]" if f.get("stalled") else "", f.get("reason", "")))
                act = input("\n输入编号移除该项，输入 a 全部清除，回车返回：").strip()
                if act.lower() == "a":
                    save_failures({"items": []})
                    print("失败队列已清空。")
                elif act.isdigit() and 1 <= int(act) <= len(fails):
                    ident = fails[int(act) - 1].get("identifier")
                    doc = load_failures()
                    doc["items"] = [f for f in doc.get("items") or [] if f.get("identifier") != ident]
                    save_failures(doc)
                    print("已移除：%s（下轮可重试）" % ident)
        elif choice == "16":
            try:
                os.remove(PROGRESS)
                print("断点进度已清除，下次全流程从头执行。")
            except OSError:
                print("（无断点进度）")
        elif choice == "17":
            doc = load_json(config.MARKETPLACES_FILE) or {}
            found = False
            for m in doc.get("markets", []):
                hint = m.get("ai_hint")
                mr = (hint or {}).get("manual_request") if isinstance(hint, dict) else None
                if mr:
                    found = True
                    print("  %s  %s：" % (m.get("id"), m.get("name")))
                    for f, reason in mr.items():
                        print("      %s → %s" % (f, reason))
            if not found:
                print("（无 manual_request 建议项）")
            print("处理方式：编辑 docs/marketplaces.json 修正字段后，删除该条目的 ai_hint.manual_request（恢复自动修正）。")
        elif choice == "0":
            break


def cmd_push():
    if not os.path.exists(os.path.join(ROOT, ".git")):
        print("当前目录还不是 git 仓库。首次推送请先完成初始化：")
        print("  cd \"%s\"" % ROOT)
        print("  git init")
        print("  git add -A")
        print("  git commit -m \"init: DSH 万市枢纽\"")
        print("  git branch -M main")
        print("  git remote add origin https://github.com/TeaClearInkII/DSH-Marketplaces-Nexus.git")
        print("  git push -u origin main")
        print("（GitHub 仓库需先创建；之后日常更新可直接用本菜单 [12] 推送）")
        return 1
    try:
        subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
        subprocess.run(["git", "commit", "-m", "pipeline: 自动更新数据 %s" % now_iso()[:10]], cwd=ROOT, check=True)
        subprocess.run(["git", "push"], cwd=ROOT, check=True)
        print("已提交并推送。")
    except Exception as e:
        print("push 失败：%s（可能无变更或无远程仓库）" % e)
        return 1
    return 0


def cmd_unexclude(ident):
    ident = norm_identifier(ident)
    excl = load_json(EXCLUSIONS, {}) or {}
    items = [e for e in excl.get("items") or [] if e.get("identifier") != ident]
    excl["items"] = items
    excl["updated_at"] = now_iso()
    save_json(EXCLUSIONS, excl)
    changelog({"action": "unexclude", "identifier": ident})
    print("已从排除名单移除：%s" % ident)


def apply_set_args(pairs):
    """把 KEY=VALUE 写入仓库根 .env（已有键则替换，新键追加）。"""
    env_path = os.path.join(ROOT, ".env")
    lines = []
    try:
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        pass
    for pair in pairs:
        if "=" not in pair:
            print("忽略无效项（需 KEY=VALUE）：%s" % pair)
            continue
        k, _, v = pair.partition("=")
        k, v = k.strip(), v.strip()
        if not k:
            continue
        found = False
        for i, line in enumerate(lines):
            s = line.strip()
            if s and not s.startswith("#") and "=" in s and s.split("=", 1)[0].strip() == k:
                lines[i] = "%s=%s\n" % (k, v)
                found = True
                break
        if not found:
            lines.append("%s=%s\n" % (k, v))
        print("[env] %s=%s" % (k, v))
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def main():
    ap = argparse.ArgumentParser(description="DSH 万市枢纽全自动流水线")
    ap.add_argument("--unexclude", metavar="IDENT", help="从排除名单移除 identifier")
    ap.add_argument("--set", action="append", metavar="KEY=VALUE", help="写入 .env 配置（可多次），如 --set AI_MAX_CALLS=30")
    args, _ = ap.parse_known_args()
    if args.set:
        apply_set_args(args.set)
        print("配置已写入 .env，下次运行 pipeline 生效。")
        return 0
    if args.unexclude:
        return cmd_unexclude(args.unexclude)
    cmd = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "menu"
    if cmd == "run":
        return run_pipeline()
    if cmd == "push":
        return cmd_push()
    return cmd_menu()   # 默认进入主菜单


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
