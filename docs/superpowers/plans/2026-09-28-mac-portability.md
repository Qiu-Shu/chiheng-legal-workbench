# M 芯片 Mac 法律库迁移实施计划

> **For agentic workers:** 使用 subagent-driven-development 按任务实施；先规格复核，再独立质量复核。本项目无 Git，不建仓、不伪造提交。用户已于 2026-09-28 确认 docs/mac-portability-audit.md 的方案。

**Goal:** 在不改写法律版本、不丢原件、不复制账号的前提下导出并恢复个人法律库，生成目标 Mac 的安装与服务配置。

**Architecture:** 延用 SQLite backup、ZIP、逐文件 SHA256 和现有只读 MCP。源码与个人数据分包；迁移是独立副本，不做双向同步。恢复必须拒绝已存在的目标目录，验证成功后再交付新目录。

**Tech Stack:** Python 标准库、SQLite/FTS5、现有 Scrapling/MCP、macOS 用户级 LaunchAgents。

**本轮完成记录（2026-09-28）：** 下列实现与本机验收任务完成。24项迁移、14项路径配置、26项安装器测试及全量280项通过；431文件真实快照恢复、实际search安装、两个恢复目录7工具/39全文通过。Task 3 的干净环境验收仅search/PDF；完整Scrapling/浏览器依赖安装因下载问题未验收。服务配置已生成但本机不激活第二套服务；第二台Mac及真实重登录明确待外部设备验收。交付与两项目记忆已同步。

## 任务一：安全数据快照与恢复

文件：新增 `library_transfer.py`、`scripts/transfer_library.py`、`tests/test_library_transfer.py`。

- [x] 先写失败测试：`export_library(root, archive)` → `restore_library(archive, target)`，用带 provenance 和 audit 的真实临时 SQLite，核对正文、来源、状态和原件；测试损坏、额外文件、重复成员、越界、符号链接、已存在目标、采集锁忙和缺文件。
- [x] 运行 `.venv/bin/python -m unittest discover -s tests -p test_library_transfer.py -v`，确认红灯来自缺功能。
- [x] 实现两个公开函数和 CLI：`export --root PATH --archive PATH`、`restore --archive PATH --target PATH`、`verify --archive PATH`。只包显式公开法源 data 子目录/文件、必要配置、调度状态；未知 data 项拒绝而非漏打包。旧外部镜像单独复制到包内，配置改为相对于配置文件的路径，不改当前配置。原件/历史元数据不重写。
- [x] 导出拿现有采集/调度锁，SQLite 用一致性 backup；导出前后文件集合/哈希与数据库逻辑摘要比对，不一致则失败。普通读取服务不停机；新增手动写操作不得与导出同时进行。保留许可与来源说明，排除日志、缓存、账号、虚拟环境。
- [x] 恢复先检查有限文件数/大小、成员路径、大小写冲突、清单一致性/哈希、必需数据库和镜像，校验库完整性、核心表和全文哈希；不执行包内代码。暂存到目标旁，成功后无覆盖交付，任何失败保留源库和已有目标。
- [x] 定向测试全部通过后规格与安全复核；缺口修复再进入下一任务。

## 任务二：运行位置和依赖解耦

文件：新增 `local_settings.py`、`tests/test_local_settings.py`；修改 `legal_mcp.py`、`legacy_doc.py`、`official_pdf.py`、`scripts/export_obsidian_library.py`、`scripts/integrity_report.py`、`scripts/ingest_basic_laws.py`；核对 `scripts/refresh_upstream_catalog.py` 的相对路径语义；依赖清单。

- [x] 先写失败测试：镜像相对配置文件定位、不依赖当前工作目录；工具优先显式设置再自动发现；Obsidian 未配置时明确跳过、配置后不得覆盖非托管笔记。
- [x] 使用 `resolve_config_path(config_path, value)` 统一路径解释。机器配置与可携带公共来源配置分开，不打包机器专用设置。旧绝对配置在本机继续兼容。
- [x] 从当前实际导入环境核对 PDF 依赖版本，补齐受测版本；不将旧环境整个复制。外部国家库客户端保留独立可选接入，缺失须明确说明，不假装离线迁移自动带来联网连接。
- [x] PDF抽取保持独立有超时的子进程与原有安全检查，但目标解释器不再强依赖 Codex 缓存；优先受测项目环境。测试夹具的 reportlab 也在开发验收依赖中声明。
- [x] 运行新测试和既有全量工程验收，确认本机7个工具仍可用。

## 任务三：目标 Mac 安装预检与配置

文件：新增 `scripts/install_mac.py`、`tests/test_mac_install.py`、`docs/mac-migration-guide.md`。

- [x] 先测试 Apple Silicon/操作系统/依赖检查、中文空格路径、生成 plist 的参数数组、已有服务/端口冲突拒绝、安装失败不覆盖旧库。
- [x] 安装入口先只读预检，再以显式操作建立新目录运行环境和配置。未核验前不启用更新任务；本机演练不注册第二套相同服务、不抢占18063端口。
- [x] 输出目标电脑所需依赖安装步骤、只读服务/调度配置及独立恢复说明。能自动执行的步骤提供明确入口；缺目标设备不能冒充已经在那里安装。
- [x] 对已恢复目录执行干净依赖安装与7工具检验；分别记录环境重建、源码/数据恢复、服务配置生成、真实登录启动的验收层级。

## 任务四：实库演练、交付与记忆

- [x] 用实际数据库和原件生成个人数据包，换中文含空格目录恢复；核对所有版本、原件哈希、旧镜像和来源/审计记录。
- [x] 重复恢复/残缺包演练拒绝覆盖；本机原服务只读冒烟测试。
- [x] 完成独立质量复核、全量测试；交付源码/个人数据清单和中文操作说明，更新两项目 Obsidian 最近状态。
- [x] 明确未验收项：第二台 Mac、真实重启/登录、云端入口和多机同步。不得与库覆盖率、法律效力审核混淆。
