# DSH 万市枢纽（DSH Marketplaces Nexus）

> DSH 生态的「市场集」—— 收录插件市场、插件市场网站和精选库，一键发现全生态。
> 数据由**全自动流水线**维护：多源发现 → AI 初筛 → 自动收录 → AI 修正 → 数值刷新。

## 界面

![界面](界面.png)

## 这是什么

- **只收录市场级资源**：插件市场、插件市场网站、精选库；不直接收录单个插件。
- **数据来源**：GitHub 搜索 + awesome 精选库 + 社区 Issue 建议；AI 初筛（置信度 ≥ 0.85 自动收录，低置信进待复核池）；AI 修正白名单字段；脚本刷新数值。
- **数据诚实**：无法获取的字段保持 null，不编造；AI 拿不准的字段标记「建议人工处理」（`manual_request`）。

## 安装与使用

```sh
# 安装
dsh plugin --profile web add dsh-marketplaces-nexus

# 更新
dsh plugin --profile web update dsh-marketplaces-nexus

# 启用/禁用（DSH 无原生命令）：编辑 <profile>/cordis.patch.yml 添加
#   - id: nexus-market-panel
#     name: dsh-marketplaces-nexus
#     disabled: true
# 删除 disabled 行即恢复启用

# 卸载
dsh plugin --profile web remove dsh-marketplaces-nexus
```

安装/更新/卸载后**重启 DSH**，进入 设置 → 万市枢纽。

- 面板直接读取本仓库 `docs/marketplaces.json`（远程 raw）：仓库推送数据更新后面板自动刷新，**无需重装插件**。
- `npm publish` 仅在**面板代码变更**时执行；数据更新只需推仓库。

## 提交新市场

推荐直接提交 Issue（自动进入流水线候选池，无需人工改数据）：

1. 新建 Issue，选择模板 **ADD_MARKET**
2. 填写：名称、仓库/网站地址、类型（插件/插件市场/网站/精选库）、备注
3. 流水线下次运行时自动完成发现、初筛、收录或进入待复核池

收录标准：**市场级资源**（能发现/安装/列举多个插件的来源）；单个插件不收录。

## 数据与条目模板

| 文件 | 说明 |
| :--- | :--- |
| `docs/marketplaces.json` | 完整市场列表（Schema v2.5.0，id 为 m-XXXX 编号） |
| `docs/summary.json` | 统计摘要（总数/分类计数/活跃数，面板快速加载用） |
| `schema/schema.json` | JSON Schema 定义（v2.5.0） |
| `data/` | 流水线中间产物（排除名单/待复核/失败队列/变更日志，不发布） |

一条条目的结构（取自真实数据 m-0001）：

```json
{
  "id": "m-0001",
  "name": "DSH Find 插件搜索",
  "description": "在 DSH 生态中搜索插件，按星标排序，提供简介和安装命令。",
  "icon": "https://github.com/awesome-dsh-plugin.png",
  "homepage": "https://github.com/awesome-dsh-plugin/dsh-find-plugin",
  "categories": ["plugin"],
  "tags": ["插件搜索", "GitHub", "DSH"],
  "popularity": { "github_stars": 38, "stars_delta": 2, "rank": null },
  "item_count": null,
  "status": "active",
  "last_plugin_update": "2026-08-14T13:17:47Z",
  "data_source": {
    "type": "github_repo",
    "identifier": "awesome-dsh-plugin/dsh-find-plugin",
    "last_sync": "2026-08-17T00:24:32Z"
  },
  "maintainer": "@awesome-dsh-plugin",
  "first_added": "2026-08-16T00:00:00Z",
  "refresh_interval": "daily",
  "usage_tip": "安装后重启 dsh web，直接向代理描述需求即可自动搜索插件。",
  "npm_package": "dsh-find-plugin",
  "security_note": null,
  "ai_hint": { "manual_request": { "homepage": "README 中未提供独立网站，仅 GitHub 仓库链接。" } }
}
```

字段分级（决定 AI 修正权限）：

| 级别 | 字段 | 说明 |
| :--- | :--- | :--- |
| L0 标识 | `id` | 不可修改 |
| L1 名称 | `name` | 谨慎（仅明显错误时） |
| L2 内容 | `description` / `tags` / `usage_tip` / `npm_package` | AI 可修正 |
| L3 元数据 | `popularity` / `item_count` / `status` / `last_plugin_update` | 脚本维护，AI 不碰 |

`manual_request`：AI 拿不准时标记，流水线跳过该字段自动修正；人工处理后删除标记即恢复。

分类（`categories` 可多选，第一个为主分类）：

| 分类 | 含义 |
| :--- | :--- |
| `plugin` | 插件（会话内搜索/发现类） |
| `marketplace` | 插件市场（DSH 内安装的市场） |
| `website` | 插件市场网站（独立发现站） |
| `library` | 精选库（awesome 类目录） |

## 开发信息

```sh
# 一键全自动流水线（推荐）
python collector/pipeline.py

# CLI 菜单：排除名单 / 待复核 / 失败队列 / 配置 / 报告 / 推送
python collector/pipeline.py menu

# 配置（写入 .env）
python collector/pipeline.py --set AI_MAX_CALLS=30
```

环境要求：Python 3.9+（标准库）、`GITHUB_TOKEN`、`DEEPSEEK_API_KEY`（`.env` 或环境变量）。

完整流程与机制说明见 [docs/PIPELINE.md](docs/PIPELINE.md) 与 [collector/README.md](collector/README.md)。

### 目录结构

```
.
├── docs/                  # 发布数据（marketplaces.json + summary.json + PIPELINE.md）
├── schema/                # JSON Schema v2.5.0
├── data/                  # 流水线中间产物（不发布）
├── collector/             # 流水线脚本（pipeline.py 一键）
├── plugin/                # DSH 面板插件（npm bundle 包）
├── .github/               # Issue 模板（ADD_MARKET）
└── archive/               # 归档（不提交）
```

## 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。
