# data/ 目录说明

本目录存放**流水线中间产物**，不对外发布（见根目录 `.gitignore`）。

| 文件 | 说明 |
| :--- | :--- |
| `candidates.json` | 旧采集脚本候选池（pipeline 已取代，可删除） |
| `scan-report.json` | 每轮汇总报告（pipeline 阶段 6 输出） |
| `marketplaces.tmp.json` | 旧管理台临时编辑文件（已归档，可删除） |
| `exclusions.json` | **排除名单**：AI 判定单插件（identifier/原因/复核次数/稳定标记） |
| `pending.json` | **待复核池**：低置信候选，再次判定 market 才收录 |
| `failures.json` | **失败队列**：网络/AI/复核失败，连续 3 次自动暂停重试 |
| `changelog.jsonl` | **变更日志**：每次数据变更一行（时间/编号/字段/旧→新/阶段） |
| `pipeline.log` | 轮次日志（本地时区，阶段耗时/成本/错误） |
| `stage_found.json` | 发现结果暂存（单阶段执行复用） |
| `stage_screen.json` | 初筛 market 列表暂存 |
| `stage_progress.json` | 断点进度（异常中断后续跑） |
| `.pipeline.lock` | 防并发锁（PID + 30 分钟超时自动清理） |

## 生命周期

```
发现（stage_found.json）
    ↓
AI 初筛 → 排除名单（exclusions.json）/ 待复核（pending.json）/ 失败（failures.json）
    ↓
自动收录 → docs/marketplaces.json（正式数据）+ docs/summary.json
    ↓
AI 修正 + 数值刷新 → changelog.jsonl（变更留痕）+ pipeline.log（运行留痕）
```

## 注意事项

- 排除名单的 `stable: true` 表示不再复核；误排除可用 `pipeline.py menu` [8] 移除。
- 失败队列的 `stalled: true` 表示暂停自动重试，菜单 [15] 可手动恢复。
- `stage_progress.json` 存在表示上次运行未完整结束；整轮完成自动清除。
