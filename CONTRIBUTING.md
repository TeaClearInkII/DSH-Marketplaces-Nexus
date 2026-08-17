# 贡献指南

感谢你对 DSH 万市枢纽的关注！本仓库收录 DSH 生态的插件市场、导航站和精选库，数据由全自动流水线维护。

## 我能贡献什么

- **推荐新市场**：发现新的插件市场、导航站或精选库？提交 Issue（选择「新增市场」模板）。流水线会自动读取 Issue 中的 GitHub 链接进入候选池，AI 初筛通过即收录。
- **修正数据**：描述不准确、链接失效、状态变化？直接修改 `docs/marketplaces.json` 提交 PR（或告诉我，流水线 AI 修正会覆盖大部分字段）。
- **处理 manual_request**：运行 `python collector/pipeline.py menu` → [17]，按 AI 标记处理条目后删除 `ai_hint.manual_request`。
- **参与开发**：流水线、面板、工作流的改进。

## 收录标准

1. 必须是「市场」级资源：插件、插件市场、插件市场网站、精选库；**不接受单个插件**（AI 初筛会进排除名单）。
2. 与 DeepSeek Harness 生态直接相关。
3. 提供真实的链接（GitHub 仓库或可访问的网站）。

## 数据规范

- 数据文件必须符合 `schema/schema.json`（v2.5.0）。
- `id` 为流水线分配的编号（`m-XXXX`），全局唯一；匹配/去重基于 `data_source.identifier`。
- `categories` 至少一个，取值：`plugin`（插件）、`marketplace`（插件市场）、`website`（插件市场网站）、`library`（精选库）；一条目可属多类，第一个为主分类。
- 简介（`description`）**不含数字统计**——数字只进 `item_count`（由脚本/AI 维护）。
- 未巡检的动态字段（`github_stars`、`item_count` 等）填 `null`，禁止编造。
- AI 输出仅作参考，均记录在 `ai_hint`；人工修改的字段注意 AI 修正可能覆盖（如需锁定，见 manual_request 机制）。

## 贡献流程

1. **推荐新市场**：提交 [Issue](./.github/ISSUE_TEMPLATE/ADD_MARKET.yml)，流水线自动读取并初筛，通过即自动收录。
2. **修正数据**：直接 PR 修改 `docs/marketplaces.json` + 同步 `docs/summary.json`。
3. **数据类 PR 标题**：`data: 新增/更新 <market id>`；一 PR 一主题。
4. **推送前检查**：`git status` 确认无误后 `python collector/pipeline.py push`（或手动 `git push`）。
