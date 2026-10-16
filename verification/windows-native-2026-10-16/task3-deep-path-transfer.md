# Task 3 前置 — Windows 深路径公开库传输

日期：2026-10-16。基线 `0f9c25909c9eba64e0b6930af1937a470a9d493d`。本阶段只修复已实测的公开库传输失败，尚不代表新交付包或新安装验收完成。未提交、安装新依赖、修改系统策略或注册表；原下载包、首次失败安装与真实资料均保留。

最终验证：完整离线入口 **632项，625通过、7明确跳过，85.360秒，退出0**。新增3项Windows原生深路径回归全部实际运行。原公开归档590个载荷在最长300字符路径处恢复、重导出和验证成功；公开载荷摘要、数据库逻辑内容、来源和镜像状态保持。

## 根因与最小修复

Task2在源码下的深路径恢复报 `FileNotFoundError`，首个合成回归在合法归档成员的 `path.open('xb')` 同样失败：1项ERROR、退出1。归档相对路径及每个组件均合法，超出的是包含临时暂存目录后的完整Windows路径。

本机313字符合成路径实验中，普通文件写入失败；扩展路径成功。SQLite普通 `file:///C:/...` URI在该长度也无法打开，`Path.as_uri()`直接处理扩展路径会把问号当成主机而报 `invalid uri authority: %3F`。`file:`加百分号编码的扩展路径可以读取，并由 `mode=ro` 拒绝写入。最早226字符探针未达到长路径边界，仅作前置观察；313字符探针才验证这一判断。

- `library_transfer._io_path` 只为内部Windows I/O统一绝对路径、词法归一化和扩展路径；复用已有 `_safe_name` 拒绝Windows不安全组件。归一化不跟随链接，随后祖先 `lstat` 本身也使用可处理长路径的路径。
- export、restore、verify及配置引用的公开镜像路径复用该入口；`config/../data`在加扩展前缀前完成词法归一化。暂存目录保留扩展路径，避免成功或失败清理时再触发路径限制。
- SQLite只读入口用标准库 `quote` 编码Windows路径，保留 `mode=ro`、`query_only`、`trusted_schema` 控制；未改成可写连接。非Windows继续使用原file URI流程。
- 归档成员、manifest、相对镜像配置、公共资料白名单、哈希检查、写锁及原子拒绝覆盖不变。旧reparse模拟夹具适配内部扩展路径，另新增真实深目录junction拒绝检查。

## 验证证据

所有下列命令均在独立持衡仓库运行，Python为现有 `.venv/Scripts/python.exe`（3.13.16）。日志本机保留，受既有 `*.log` 忽略规则排除；没有把未运行项目计为通过。

| 检查 | 实际结果 | 退出码 | 证据 |
| --- | --- | --- | --- |
| 最小深路径RED，`-B -m unittest tests.test_library_transfer.LibraryTransferTests.test_windows_deep_restore_preserves_hashes_and_can_be_exported_again -v` | 1项ERROR，`path.open('xb')`长路径失败，0.207秒 | 1 | `task3-deep-path-red.log` |
| 同一回归修复后 | 1/1通过，0.319秒 | 0 | `task3-deep-path-green.log` |
| 原生路径/SQLite探针 | 313字符普通文件和普通URI失败；编码扩展URI读成功，写拒绝 | 0 | `task3-deep-path-probe-extended.log`、`task3-deep-path-sqlite-uri-probe.log` |
| 首次关联回归 | 56项，53通过、2ERROR、1POSIX skip：错误模块名 `test_windows_installer` 与旧reparse故障注入只匹配普通路径 | 1 | `task3-transfer-targeted-initial.log` |
| 更正模块名及夹具，`-B -m unittest tests.test_library_transfer tests.test_windows_install tests.test_windows_portability tests.test_windows_private -v` | 84项，83通过、1POSIX skip，26.434秒；此后补充真实深junction正式用例，由下行完整回归覆盖 | 0 | `task3-transfer-targeted.log` |
| 原公开ZIP在新深目录恢复→重导出→verify | 590载荷，最长300字符；原包与公开内容保持 | 0 | `task3-public-deep-roundtrip.log`、`task3-public-deep-roundtrip.json` |
| 无预设 `PYTHONUTF8`，`-B scripts/test_windows_offline.py` | **632项，625通过、7skip，85.360秒** | **0** | `task3-full-offline.log` |
| `git diff --check` | 通过 | 0 | 本次终端记录 |

正式新增回归覆盖中文、空格、`#`和`%`路径；分别让成员路径和库根路径超过260字符；恢复后重导出及verify；关闭 `query_only` 后仍拒绝写入；缺失SQLite不新建；损坏归档不发布并清理暂存；深祖先真实junction在解包前拒绝，外部哨兵不变。独立Spec代理另以6项本机合成探针验证深归档位置、拒绝覆盖和发布竞态；其证据单列，不并入632项分母。

7项skip与Task2相同：2项POSIX mode位、2项POSIX凭据文件flags/FIFO/owner、1项POSIX flock、1项macOS转换器、1项本机未装LibreOffice的真实DOC转换。Windows原生私有文件8项实际通过。离线入口仅保护测试进程常用TCP、asyncio和Fetcher入口，非系统级联网沙盒。

## 原公开归档复验

新建开发副本位于 `.local/task3-public-deep-roundtrip-20261016/公开库 中文 空格 #100%`；新导出为同父目录 `verified-public-roundtrip.zip`。两者均与原库隔离，保留供复核。

原 `personal-public-library.zip` 前后SHA-256均为 `50bb70dd01b6432b6fdc946fcf17c8afb075cbf26258edbc6ed460b02c38e791`。数据库版本、来源、全文索引各49，审计100；SQLite备份物理字节允许变化，逻辑摘要 `82b6a97660190154d5ac72df38e2b2bd817c40f2aa6705e3ea9bb8b74765c3be`一致。其余各公开载荷摘要保持。镜像2190版本、77809文本单元，仍为 `unverified_mirror`，未推断再分发许可或法律核验状态。

此修复范围是公开库传输。未声称全部应用模块或第三方程序支持任意深安装路径；新候选构建与全新中文空格目录安装、宿主连接、实际网站登录、计划任务启动仍须分别验收。本轮未重跑JS边界，因为没有修改浏览器代码；Task2已有12/12通过的独立证据。
