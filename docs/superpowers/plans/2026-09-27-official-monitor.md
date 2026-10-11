# 固定官方原件监测实施计划与记录

依据：../specs/2026-09-27-known-original-monitor-design.md；用户已批准。

1. 冻结21份基线，编写变化、失败、历史保留、锁、超时与下载边界测试；先失败再实现。
2. 实现原件与字段比较，只保存独立监测快照，不写法律SQLite；接入现有national任务及Obsidian。
3. 真实检查21份，确认数据库未改变；全量测试、独立复核、更新交付和小记忆。

接口预检：固定配置→监测报告→调度退出码→Obsidian摘要。失败需返回非零但看板仍更新；月度流程不改。

Ruling: 本项目无Git仓库，沿用现有项目目录，保留实施记录而不执行worktree/提交/删除工作区 — 避免凭空创建或删除项目历史 — 代价是本轮没有Git级隔离，靠精确文件范围、测试及交付哈希留痕。

## 验收记录

- Task 1: complete — 固定21份配置；新模块缺失导致首轮失败；9项核心测试转绿。
- Task 2: complete — 下载和调度测试先失败，接入后15项监测、22项调度/来源测试通过。
- Task 3: complete — 真实21份全部未变，首轮SQLite SHA前后相同；真实national四步骤退出0，Obsidian已导出。
- Final: fixed 启动前失败留下旧成功 — test_bad_configuration_marks_attempt_failed_without_losing_history RED→GREEN。
- Final: fixed 中断后远端恢复导致待审丢失 — test_crash_after_snapshot_write_keeps_pending_on_remote_reversion RED→GREEN；先登记待审再写文件，报告提示可能待补全。
- Final: fixed 详细日志泄露签名 — test_verbose_http_logging_cannot_leak_signed_url RED→GREEN。
- Final: fixed 接口及解压大小不受控 — test_json_api_is_size_bounded_and_checks_api_status、test_unexpected_compression_rejected_before_reading_document RED→GREEN。
- Final suite: 132/132通过，无失败/错误/跳过。独立复核报告verification/official-monitor-code-review.md；修复未二次独立复核。无延期小项，无拒绝判断事项。
