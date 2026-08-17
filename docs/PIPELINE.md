# DSH 万市枢纽 · 全自动数据流水线（PIPELINE）

> 版本：2.0 · 状态：已实施（首轮全流程验证通过：1338 发现 / 11 新增 / 3 排除 / 21 修正 / 0 错误）
> 触发：`python collector/pipeline.py`（主菜单）或 `python collector/pipeline.py run`（直接执行）

## 一、目标

「发现 → 初筛（排除名单）→ 收录 → 修正 → 刷新 → 报告」全自动，无人工审核环节；
CLI 菜单兜底人工查看/干预；失败可追溯、断点可续跑。

## 二、数据模型

### 2.1 id 编号化
- 条目 id 统一为 `m-XXXX`（流水线首次运行自动迁移旧 id，写 changelog）
- 匹配/去重基于 `data_source.identifier`（owner/name 归一化）
- 面板不展示 id，无影响

### 2.2 字段分级（AI 可碰性）
| 等级 | 字段 | AI 行为 |
| :--- | :--- | :--- |
| L0 标识 | `id` | 不可碰 |
| L1 展示 | `name` | md 提及更优名且置信高才建议改 |
| L2 内容 | `description / categories / tags / usage_tip / homepage / item_count / status / npm_package` | 可改；homepage 提取标注来源；npm_package 需 registry 校验 |
| L3 元数据 | `popularity / data_source / first_added / refresh_interval / maintainer` | 脚本维护 |
| 拿不准 | `ai_hint.manual_request` | 标记待人工处理，流水线跳过该条目自动修正 |

### 2.3 数据文件（均不提交，见 .gitignore）
```
data/exclusions.json       排除名单（identifier/原因/复核次数/stable/时间戳）
data/pending.json          待复核池（低置信，再次判定 market 才收录）
data/failures.json         失败队列（网络/AI/复核失败，连续失败自动暂停）
data/changelog.jsonl       每次变更一行（时间/编号/字段/旧→新/阶段）
data/pipeline.log          轮次日志（本地时区，含阶段耗时/成本/错误）
data/scan-report.json      每轮汇总报告
data/stage_found.json      发现结果暂存（单阶段执行复用）
data/stage_screen.json     初筛 market 列表暂存
data/stage_progress.json   断点进度（续跑用）
data/.pipeline.lock        防并发锁（PID + 超时自动清理）
```

## 三、字段规则

- **简介不含数字**：AI 提示词禁止；数字只进 `item_count`
- **防震荡**：修正写入前与 `ai_hint.ai_refine` 上次值对比，相同跳过
- **manual_request**：AI 拿不准 → 标记 + 跳过自动修正；人工处理后删除标记恢复
- **npm 包名**：AI 提取 → registry 校验存在 → 才写入；否则命令自动用 `github:identifier`
- **排除名单稳定**：连续 3 次复核仍 plugin → stable 不再复核；星数翻倍强制重评；复核带 1 小时冷却防横跳
- **失败节流**：同项连续失败 ≥3 → stalled 暂停自动重试（菜单可手动恢复）

## 四、流程与命令

### 4.1 全流程阶段
```
0 环境检查   token / DeepSeek 余额 / GitHub 限流 / 网络 / 锁
1 发现        GitHub 搜索（stars+updated）+ awesome json + 本仓库 Issues 建议
2 AI 初筛      market/maybe/plugin + 置信度 → 排除名单 / 待复核池
3 自动收录     market ≥0.85 入库（编号 + identifier 去重）
4 AI 修正      白名单字段 / 防震荡 / 数字清理 / manual_request
5 数值刷新     stars / pushed_at / README 链接数 / 网站统计 / summary
6 报告         变更日志 + 成本合计 + 失败通知
```

### 4.2 CLI
```
python collector/pipeline.py              # 主菜单
python collector/pipeline.py run          # 直接执行全流程（计划任务用）
python collector/pipeline.py push         # git 提交推送
python collector/pipeline.py menu         # 主菜单
python collector/pipeline.py --set KEY=VALUE   # 写 .env 配置（可多次）
python collector/pipeline.py --unexclude ID    # 移除排除项
```

### 4.3 主菜单（17 项）
```
[1]  执行全流程（断点续跑）      [10] 查看待复核池
[2]  仅发现                      [11] changelog 摘要
[3]  仅 AI 初筛                  [12] git 提交推送
[4]  仅自动收录                  [13] 查看/修改配置（.env）
[5]  仅 AI 修正                  [14] 查看最近报告
[6]  仅数值刷新                  [15] 查看/清理失败队列
[7]  浏览排除名单                [16] 清除断点进度
[8]  移除排除项                  [17] 查看 manual_request（人工处理项）
[9]  添加排除项                  [0]  退出
```

## 五、失败处理

| 场景 | 处理 |
| :--- | :--- |
| 网络/SSL 失败 | 自动重试 3 次（指数退避），仍失败记录失败队列 |
| AI 调用失败 | 记录失败队列；连续 3 次自动暂停（stalled），菜单可恢复 |
| pending 复核 3 次未通过 | 归档到失败队列（kind=review），不再丢弃 |
| 单页搜索失败 | 跳过该页继续 |
| 整体异常 | 报告 errors + 退出码 1（数据不动） |
| 致命（缺 key/余额/锁） | 退出码 2 |
| 锁残留（强杀） | PID + 超时（30 分钟）自动清理 |
| 中断续跑 | 断点进度自动记录，重跑跳过已完成阶段 |

退出码：`0` 成功无异常（可 push）/ `1` 完成但有异常 / `2` 致命。

## 六、成本控制

- 单次 AI 调用 ≈ ¥0.003（实测 4226 输入 + 132 输出 token）
- 每轮 AI 调用上限 `AI_MAX_CALLS=20`（可配）
- 日志每行 `[ai-cost]` 附带本次运行累计成本；结束汇总 `AI 成本合计 ≈ ¥X.XXXX`
- 默认上限：输入 8000 字符（`DEEPSEEK_INPUT_CHARS`）、输出 800 token（`DEEPSEEK_MAX_TOKENS`）

## 七、时间

- 日志/变更记录：**本地时区**（含偏移，如 +08:00）
- 数据文件 `generated_at`：UTC（标准，跨时区一致）

## 八、实施状态

- ✅ pipeline.py（阶段 0-6 + 菜单 17 项 + push + --set + 失败队列 + 断点续跑 + 成本累计）
- ✅ 首轮全流程验证通过（2026-08-16）
- ✅ README / CONTRIBUTING / collector README / 本文件同步
- ⏳ GitHub 仓库创建与推送（用户操作）
- ⏳ 插件发布（npm publish 或仓库根直装）
