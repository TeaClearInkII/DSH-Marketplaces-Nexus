# -*- coding: utf-8 -*-
"""DSH 万市枢纽 —— 采集配置

所有可调参数集中在此；敏感项（token / API key）自动探测：
  环境变量 → 仓库根 .env → GitHub CLI（gh auth token）
"""

import os
import subprocess

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COLLECTOR_DIR = os.path.dirname(os.path.abspath(__file__))


# ── token / API key 自动获取 ─────────────────────────────────────────────────

def _env_or_dotenv(key):
    v = os.environ.get(key, "")
    if v:
        return v.strip()
    for p in (os.path.join(ROOT_DIR, ".env"), os.path.join(_COLLECTOR_DIR, ".env")):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    name, _, value = line.partition("=")
                    if name.strip() == key:  # 精确匹配，避免 GITHUB_TOKEN_FOO 污染
                        return value.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def _gh_token():
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return ""


# GitHub Token：环境变量 → .env → gh CLI（任一生效即可）
GITHUB_TOKEN = _env_or_dotenv("GITHUB_TOKEN") or _gh_token()

# DeepSeek API Key（AI 初筛用）：环境变量 → .env
AI_API_KEY = _env_or_dotenv("DEEPSEEK_API_KEY")


# ── GitHub API ──────────────────────────────────────────────────────────────
GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
TOPIC = "dsh-plugin"                                       # 搜索话题
AWESOME_JSON_URL = "https://awesome-dsh-plugin.com/plugins.json"

# ── 关键词过滤（分级）────────────────────────────────────────────────────────
# 强市场词：命中即保留（除非同时命中强排除词）
KEYWORDS_STRONG_INC = [
    "market", "marketplace", "plugin hub", "plugin market",
    "catalog", "directory", "radar",
    "精选", "聚合",
]
# 弱市场词：命中且无任何排除词才保留
KEYWORDS_WEAK_INC = [
    "awesome", "find", "discover", "registry", "collection",
    "plugins.json", "plugin-list", "navigation", "hub", "index",
    "生态", "社区", "导航", "集合", "合集", "市场",
]
# 强排除词：命中即剔除（单插件/单产品硬特征）
KEYWORDS_STRONG_EXC = [
    "sidebar", "memory", "skin", "ads", "game", "toy", "resume",
    "desktop", "browser-extension", "companion", "content-discovery",
    "agent-os", "playground", "sandbox", "k8s", "kubernetes",
    # 单功能插件强特征（名称/描述/话题命中即剔除）
    "login", "preview", "terminal", "bridge", "provider",
    "guard", "quant", "background-plugin", "sticky-disclosure",
]
# 弱排除词：压制弱市场词（不压制强市场词，避免误伤真市场）
KEYWORDS_WEAK_EXC = [
    "tool", "cli", "skill", "workflow", "template", "agent",
    "agents", "chat", "mobile", "extension", "runtime", "os ",
    "macos", "windows", "docs", "learn", "demo", "example",
    "tutorial", "starter", "snippet", "canvas", "codepilot",
    "plugin-manager", "api-keys", "credentials", "tui",
    # 常见单功能插件特征（名称/描述/话题里常见）
    "stock", "a-share", "股票", "theme", "navbar", "stats",
    "usage", "gateway", "workshop", "command", "check", "suite",
    "ranking", "mcp", "cron", "notify", "color", "emoji",
    "share", "model-config", "spec", "swarm", "caliper",
    "leantoken", "zeromd", "peanut", "hologram", "recommend",
    "group-photo", "input-file", "im-gateway", "lark", "taskboard",
    "workbench", "knowledge-graph", "custom-tool", "notifier",
    "balance", "cost-meter", "status-rotator", "drag",
]

# ── 采集范围 ─────────────────────────────────────────────────────────────────
# 多轮搜索：(排序方式, 每轮最多返回仓库数)
#   stars   → 高星主流市场（保证覆盖率）
#   updated → 近期活跃（捕捉新发布、低星但值得收录的市场）
# 轮次越多覆盖越全，但请求数 = 每轮 ceil(数量/50) 次搜索请求
# （匿名搜索限 10 次/分钟，token 后 5000/小时）
# 管理台「发现新市场」可通过环境变量 DSH_SCAN_STARS / DSH_SCAN_UPDATED /
# DSH_MIN_STARS / DSH_USE_GITHUB_SEARCH / DSH_USE_AWESOME 覆盖（不修改本文件）


def _env_int(name, default):
    try:
        return int(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return default


def _env_bool(name, default):
    v = os.environ.get(name, "").strip()
    if not v:
        return default
    return v not in ("0", "false", "False", "no", "off")


SEARCH_ROUNDS = []
_stars = _env_int("DSH_SCAN_STARS", 300)
_updated = _env_int("DSH_SCAN_UPDATED", 100)
if _stars > 0:
    SEARCH_ROUNDS.append(("stars", _stars))
if _updated > 0:
    SEARCH_ROUNDS.append(("updated", _updated))
if not SEARCH_ROUNDS:
    SEARCH_ROUNDS = [("stars", 300), ("updated", 100)]

MIN_STARS = _env_int("DSH_MIN_STARS", 0)          # 最小 star 数（0 = 不过滤）
USE_GITHUB_SEARCH = _env_bool("DSH_USE_GITHUB_SEARCH", True)
USE_AWESOME_JSON = _env_bool("DSH_USE_AWESOME", True)
REQUEST_INTERVAL = 7 if not GITHUB_TOKEN else 0.5   # 请求间隔（秒），匿名时防限流

# ── AI 初步修正（DeepSeek，OpenAI 兼容）─────────────────────────────────────
AI_ENABLED = bool(AI_API_KEY)
AI_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
AI_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
AI_MAX_CALLS = 20              # 单次运行最多 AI 调用次数（限流保护）
AI_TIMEOUT = 60                # 单次调用超时（秒）
AI_MAX_TOKENS = int(os.environ.get("DEEPSEEK_MAX_TOKENS", "800"))   # 单次输出上限（token，控制成本）
AI_INPUT_CHARS = int(os.environ.get("DEEPSEEK_INPUT_CHARS", "8000"))  # 送入 AI 的文本上限（字符；输入成本极低，够用优先）

# ── 网站类条目 item_count 统计（update.py 使用）─────────────────────────────
# 从网站 HTML 中提取条数统计的正则（数字 + 单位词）
WEBSITE_STATS_PATTERNS = [
    r"([\d,]+)\s*(?:plugins?|extensions?|add-?ons?|repos?)\b",
    r"([\d,]+)\s*个?(?:插件|扩展|条目|仓库)",
]
# 网站条目候选统计路径（在首页/常见清单页依次探测）
WEBSITE_STATS_PATHS = ["", "/plugins", "/plugins.json", "/data/plugins.json", "/api/plugins"]

# ── 路径 ─────────────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(ROOT_DIR, "data")
DOCS_DIR = os.path.join(ROOT_DIR, "docs")

CANDIDATES_FILE = os.path.join(DATA_DIR, "candidates.json")     # 采集输出（待人工审核）
REPORT_FILE = os.path.join(DATA_DIR, "scan-report.json")        # 扫描报告
MARKETPLACES_FILE = os.path.join(DOCS_DIR, "marketplaces.json") # 正式数据（merge 目标）
SUMMARY_FILE = os.path.join(DOCS_DIR, "summary.json")           # 统计摘要（merge 重算）
