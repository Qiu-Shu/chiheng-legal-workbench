# 新版 Mac 迁移交付与隔离安装实施计划

> 执行方式：subagent-driven-development，任务后先规格复核，再质量复核。沿用用户已批准的2026-09-28迁移设计和当前“继续”请求。非Git目录，不建仓、不提交。本次不重新设计安装器、同步服务或云端入口。

**目标：** 重新生成包含已验收模拟法庭组件的本机个人迁移交付，在独立中文目录重新安装并运行检索和演练验证。

**架构：** 复用scripts/build_release.py的函数、library_transfer.py和scripts/install_mac.py。程序、Skill、Plugin与个人公开法库数据分包；唯一新交付目录，不覆盖旧包。干净环境安装search配置；full、第二台Mac、真实登录启动保持独立验收状态。

**技术：** 已有Python标准库、SQLite backup、ZIP及锁定依赖。没有新产品代码或依赖需求。

## Task 1：基线与重新打包

- [x] 主代理运行完整521项工程回归，保存日志和退出码。
- [x] 新建verification/mac-delivery-2026-10-09/下可复跑的交付验证助手；只作为本轮操作与证据，不改生产打包函数。读取选中文件前列出并核对路径，拒绝符号链接、敏感命名、机器配置或不明私案。Skill使用上一轮已核对的固定23文件清单，Plugin仅额外两份已检查元数据。
- [x] 在outputs下新建唯一目录，调用现有archive/build_source_archive，不能运行会覆盖旧日期交付的main。源码包确认含mock_hearing、hearing_audit、hearing_tracking、hearing_sources和CLI。补入明确选中的个人使用及本轮验收文档，留存每个成员大小和SHA256；既有tests中的合成夹具与运行记录须如实注明，不宣称匿名公开包。
- [x] 调用现有export_library(ROOT, new_archive)，使用原一致性锁、SQLite备份、原件校验和相对路径；随后verify_archive。不得改数据内容、审核状态或来源访问规则。锁忙或源数据变更时保留失败，不强行打包。
- [x] 输出本轮四包（源码、持衡Skill、Plugin、个人数据）清单；全部检验CRC、成员唯一、当前组件字节一致、排除凭据/私案/虚拟环境/机器配置。先规格、再质量审查，发现问题先修复。实查记录见verification/mac-delivery-2026-10-09/reviews.md；文件名和常见内容扫描不保证识别任意改名私密内容。

调用基于现有接口：

```python
from scripts.build_release import archive, build_source_archive
from library_transfer import export_library, verify_archive
build_source_archive(ROOT, delivery / 'program-source.zip')
archive(ROOT / 'skills/cn-litigation-redteam', delivery / 'cn-litigation-redteam.zip')
archive(ROOT / 'plugins/chiheng-legal', delivery / 'chiheng-legal-plugin.zip')
manifest = export_library(ROOT, delivery / 'personal-public-library.zip')
assert verify_archive(delivery / 'personal-public-library.zip') == manifest
```

## Task 2：本机独立安装与实际读回

- [x] 从本轮自建且已核验程序包解到本轮新目录，使用其中的install_mac.py，以当前受测原生Python创建全新search环境。目标名字包含中文和空格，父目录已存在，目标不存在。
- [x] 不使用--activate，不注册MCP、不写LaunchAgents、不停原服务。依赖从现有锁安装，失败按安装器原机制保留，不通过复制旧.venv或修改导入路径冒充干净安装。
- [x] 使用新环境的doctor，核对数据库逻辑指纹、公开原件、镜像版本和正文数量；验证实际法律片段及来源卡状态未升级。确认来源配置指向目标内镜像。
- [x] 将明确的既有6份hearing测试和合成验证脚本作为验收材料复制到目标测试目录（非私案迁移），使用目标Python实际运行86项相关测试与三个合成样例。记录实际导入文件路径，不能误用原工程代码。合成脚本仍为33轮父会话和3轮复练首轮、66项检查，引用只读本地库。
- [x] 保存安装状态、日志、证据和包哈希，旧库、旧包、服务及凭据不动。更新中文操作说明，明确Skill单包不含法库运行环境，个人数据仅自用不公开发布；Plugin元数据不等于ChatGPT上线。
- [x] 独立检查最终产物和报告，更新项目Obsidian状态。第二台Mac、full干净安装、浏览器、真实开机登录、会员认证和云端未完成，不通过本机隔离安装追认。

安装调用沿用：

```sh
python3 scripts/install_mac.py --archive /明确路径/personal-public-library.zip --target '/明确的新目录/中文 法律库' --python /明确的原生Python --profile search
```

成功条件是实际安装与测试输出，不是包生成即成功。若需要修改生产实现，应先复现并单独补最小失败测试及审查，不能在验证脚本里掩盖缺陷。

## 实际结果

四包位于outputs/chiheng-mac-2026-10-09-rlkt7h6q；证据位于verification/mac-delivery-2026-10-09。新环境安装成功，首轮验收器导入名笔误失败原样保留，另行续验成功。521工程基线、两次86目标测试、66合成检查均通过；582非DB载荷前后字节一致，DB逻辑一致。两任务规格、质量及最终报告检查通过。详docs/mac-delivery-status-2026-10-09.md；无生产代码改动。
