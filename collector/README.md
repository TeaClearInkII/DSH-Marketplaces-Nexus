# 采集脚本（collector/）

DSH 万市枢纽的数据流水线：**多源发现 → AI 初筛（排除名单）→ 自动收录 → AI 修正 → 数值刷新 → 报告**。
推荐入口：**全自动一键流水线 `pipeline.py`**（无需管理台）。

## 一键流水线（推荐）

```sh
python collector/pipeline.py                  # 主菜单（无参数默认进入）
python collector/pipeline.py run              # 直接执行全流程（计划任务用）
python collector/pipeline.py menu             # 主菜单
python collector/pipeline.py push             # git 提交推送（完成无异常时）
python collector/pipeline.py --set KEY=VALUE  # 写 .env 配置（可多次）
python collector/pipeline.py --unexclude ID   # 从排除名单移除
```

主菜单（17 项）：执行全流程（断点续跑）/ 仅发现 / 仅 AI 初筛 / 仅自动收录 / 仅 AI 修正 /
仅数值刷新 / 排除名单（浏览/移除/添加）/ 待复核池 / changelog / 推送 / 配置 /
报告 / 失败队列 / 清除断点 / manual_request 查看。

流程阶段：
0. 环境检查（GITHUB_TOKEN / DEEPSEEK_API_KEY / DeepSeek 余额 / GitHub 限流 / 防并发锁）
1. 多源发现：GitHub 搜索（topic:dsh-plugin）+ awesome 精选库 json + 本仓库 Issues（ADD_MARKET 建议）
2. AI 初筛：market / maybe / plugin 分类 + 置信度；plugin 高置信进**排除名单**（脚本特征兜底防误杀）；
   未稳定排除项带冷却复核（3 次稳定不再复核，星数翻倍强制重评）
3. 自动收录：market ≥0.85 入库（编号 id + identifier 去重）；待复核池再次判定通过才收录
4. AI 修正：已收录条目按白名单字段修正（防震荡对比 ai_hint.ai_refine、简介禁止数字、
   npm 包名 registry 校验、manual_request 标记并跳过该条目）
5. 数值刷新：stars / pushed_at / README 链接数 / 网站统计 / summary
6. 汇总报告：data/scan-report.json + data/pipeline.log + data/changelog.jsonl + AI 成本合计

失败处理：失败队列（data/failures.json）自动记录，连续失败 3 次暂停自动重试；
断点进度（data/stage_progress.json）支持中断续跑；异常退出码 1，致命退出码 2。

数据文件：`data/exclusions.json`（排除名单）、`data/pending.json`（待复核池）、
`data/changelog.jsonl`（变更日志）、`data/pipeline.log`（轮次日志）。

退出码：0 成功无异常（可 push）/ 1 完成但有异常（看报告）/ 2 致命（缺 key、余额不足、锁占用）。

## 环境变量（.env）

| 变量 | 默认 | 说明 |
| :--- | :--- | :--- |
| `GITHUB_TOKEN` | 自动探测 | GitHub API 认证 |
| `DEEPSEEK_API_KEY` | — | AI 初筛/修正（必填） |
| `DEEPSEEK_MODEL` | deepseek-chat | AI 模型 |
| `DEEPSEEK_MAX_TOKENS` | 800 | 单次输出上限 |
| `DEEPSEEK_INPUT_CHARS` | 8000 | 单次输入字符上限 |
| `AI_MAX_CALLS` | 20 | 每轮 AI 调用上限（成本保护） |
| `DSH_SCAN_STARS` / `DSH_SCAN_UPDATED` | 300 / 100 | 扫描轮次规模 |
| `DSH_MIN_STARS` | 0 | 最小星数过滤 |

## 单脚本（pipeline 内部复用）

```sh
python collector/collect.py       # 仅发现（写 data/candidates.json）
python collector/merge.py         # 候选合并（自动备份）
python collector/update.py        # 数值刷新（--out 可指定目标文件）
python collector/ai_extract.py    # AI 提取（--all / --id / --url / --apply）
```

管理台（PyQt6）已归档：`collector/gui/` → `archive/collector-gui/`（如仍保留，可
`python collector/gui/manager.py` 手动维护，但不参与流水线）。

## 规则说明

- **只收「市场级」资源**：插件市场、插件市场网站、精选库；单插件由 AI 初筛 + 排除名单剔除
- **简介不含数字**：数字统计只进 `item_count`（由脚本/AI 维护），简介永不装数字
- **防震荡**：AI 修正写入前与上次 AI 修正值对比，相同则跳过
- **manual_request**：AI 拿不准的字段写入 `ai_hint.manual_request`，汇总进报告待人工处理
- **排除名单稳定机制**：连续 3 次复核仍为 plugin → 标记稳定不再复核；星数翻倍强制重评
- **数据诚实**：无法获取的字段保持 null；AI 输出仅参考并记录 ai_hint
