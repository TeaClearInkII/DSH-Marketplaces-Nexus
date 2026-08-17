# DSH 万市枢纽插件包

DSH 生态「市场集」面板插件：在 DSH Web 设置页添加「万市枢纽」页面，聚合展示插件市场、插件市场网站与精选库，支持搜索、筛选、排序与安装管理。

## 功能

- **市场浏览**：40+ 市场条目卡片（分类/状态徽章、地址、标签、简介、标注、趋势、详情展开）
- **筛选与搜索**：分类 chips（插件/插件市场/网站/精选库）、关键词搜索（按钮/回车）、排序（星数/条目数/名称）
- **本仓库信息卡**：居中头像 + 标题、仓库名、仓库地址、标签、标注、hub 星数、收录规模、数据版本、过期提示、数据源
- **更多折叠区**：生态导航、本机环境（工作区/Profile/Node/pnpm/npm/dsh）
- **安装管理**（仅 plugin/marketplace 类）：安装/卸载（`dsh plugin` 命令，沙箱受限时 pnpm 回退）、停用/启用（直接编辑 profile bundles，无 shell 依赖）、复制安装/卸载命令手动操作

## 目录结构

```
plugin/
├── package.json         # bundle 声明：dsh.bundle.patch + dsh.client
├── cordis.patch.yml     # 插件行（id: nexus-market-panel）
├── src/
│   ├── index.js         # Host 侧：数据加载（本地→包内→远程回退）/安装管理/环境探测
│   └── client.js        # Client 侧：设置页 UI
└── docs/                # 数据快照（发布前复制，见下）
```

## 安装

```sh
# 本地源码安装（开发）
dsh plugin --profile web add ./plugin

# 或从 npm 安装（发布后）
dsh plugin --profile web add dsh-marketplaces-nexus

# 或从 GitHub 安装（需包在仓库根）
dsh plugin --profile web add github:TeaClearInkII/DSH-Marketplaces-Nexus

# 手动安装（复制命令）
dsh plugin --profile web add <包名或 github:owner/repo>
```

安装后重启 DSH，进入 设置 → 万市枢纽。

> 若自动安装因沙箱环境不可用而失败：以管理员身份运行 DSH，或在设置中切换沙箱模式为 danger-full-access（降低命令隔离），或复制安装命令在终端手动执行。

## 数据源（按优先级）

1. **工作区数据**：`<workspace>/docs/marketplaces.json`（开发/维护时直接改数据）
2. **远程 URL**：`https://raw.githubusercontent.com/TeaClearInkII/DSH-Marketplaces-Nexus/main/docs/marketplaces.json`（安装者默认数据源，随仓库推送自动更新）

> npm 包**不携带数据快照**（`files` 不含 `docs/`）：数据更新只需推送 GitHub 仓库，
> 安装者的面板自动拉取最新远程数据，**无需重新 npm publish**。
> `npm publish` 仅在**面板代码变更**时执行。

可通过插件配置覆盖远程地址：

```yaml
# 用户 cordis.patch.yml
- id: nexus-market-panel
  name: dsh-marketplaces-nexus
  config:
    dataUrl: https://raw.githubusercontent.com/TeaClearInkII/DSH-Marketplaces-Nexus/main/docs/marketplaces.json
```

## 发布

1. 更新 `package.json` 版本号（仅面板代码变更时）
2. `npm publish`
3. 用户 `dsh plugin --profile web add dsh-marketplaces-nexus`

## 开发

- 数据 Schema：仓库根 `schema/schema.json`（v2.5.0）
- 数据维护：全自动流水线 `python collector/pipeline.py`（见 `docs/PIPELINE.md`）
- 动态原型：`src/` 即最终固化版（与动态插件 nexus-1 的最新版本同步）
- 修改后本地验证：直接编辑 `src/` 并通过 `dsh plugin --profile web add ./plugin` 重新安装
