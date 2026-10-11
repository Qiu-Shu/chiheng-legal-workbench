# Task 4 独立规格审查

2026-10-11。结论：CHANGES_REQUIRED。

本次只读实现、公开交付候选、恢复目录和合成测试；仅新增本报告。没有读取真实 .env、浏览器 profile 或私案，没有修改生产数据库、Mac 服务、已安装 Skill 或旧 ZIP，没有执行真实网络业务。使用项目 `.venv/bin/python -B`；没有 Windows 机器，Windows 原生待验本身不构成此次缺陷。

## 必须修订

1. [P1] `scripts/test_windows_offline.py:20` 无条件发现全部测试，而包内仍有确定不能在 Windows 正常执行的测试夹具和断言。`docs/windows10-migration-guide.md` 直接要求目标机运行此入口，因此这会使正确安装后的离线工程检查报错，不能仅修改说明或引用 Mac 的 619 项结果关闭。

   - `tests/test_mac_install.py:182`、`:198` 对不存在于 Windows 的 `os.getuid` 使用 `patch.object` 且未设置 `create=True`。本审查在独立 Python 进程临时移除该属性，运行这两个合成测试，得到两个 `AttributeError: ... does not have the attribute 'getuid'`。没有调用 launchctl 或真实服务。Mac 激活回滚还直接依赖 getuid，宜在测试层明确平台条件，或完整模拟这个平台 API；不得修改 Mac 生产语义。
   - `tests/test_mock_hearing.py:268` 和 `tests/test_hearing_rehearsal.py:192` 的首建失败注入固定为 `os.link`，但 `mock_hearing.py:292` 的 Windows 分支实际使用 `os.rename`。在正常完成 Windows 安全前置检查后，故障注入不会触发，预期的 OSError 断言失败。应按平台注入实际发布操作，继续验证旧内容与临时文件不被破坏。
   - `tests/test_mock_hearing.py:60`、`:278`、`:282` 和 `tests/test_hearing_rehearsal.py:111`、`:230`、`:298` 混用了精确 0600/0700/0755 模式与跨平台业务行为。Windows 实现检查 DACL，`chmod(0755)` 不表示创建宽泛 DACL。只给真正 POSIX 权限断言添加平台条件，或拆成 POSIX 权限与普通会话断言；Windows 对应安全检查继续使用既有原生 ACL 用例。不得整套跳过模拟法庭、复练、事实状态、追加、来源卡或并发行为。
   - `tests/test_local_settings.py:162`、`:163` 把 PATH 发现结果固定为 `/bin/sh`，而 `local_settings.py:36` 会真实检查其文件存在与执行权限。普通 Windows 没有该文件。用 `sys.executable` 或受控的本机可执行夹具保留原 PATH 发现测试即可。同文件 `:106` 对 `/tmp/index.json` 的预期也使用 POSIX 绝对路径语义，应改为测试临时目录中的实际绝对路径。

2. [P2] 符号链接夹具未区分目标机是否允许创建链接。`tests/test_mock_hearing.py:90`、`:100`，`tests/test_hearing_rehearsal.py:226`、`:235`，`tests/test_library_transfer.py:138`，`tests/test_windows_portability.py:172` 都直接调用 `symlink_to`。Windows 普通用户若未获链接权限，测试会在创建夹具时失败，尚未触及拒绝链接的产品断言。只在夹具创建出现已知的权限/能力缺失时明确记录 skip；其他 OSError 和安全断言失败必须保留。混合用例应拆开或隔离该片段，例如 `test_windows_portability` 中后续独立的重解析点模拟不能被前面一次 skip 一并吞掉。无需要求用户提权或全局开启开发者模式。真实 Windows 重解析点行为仍单列待验。

## 发布前必要条件

当前候选为 `xia/outputs/chiheng-windows10-2026-10-11-pevq61o5/持衡-Windows10-x64-个人迁移总包.zip`，SHA-256 为 `d963f75a73fd72ea6876f23422d3ddfcbabb63afee6d27f6c949d845b1d14187`。

当前源码中的 `tests/test_p1.py`、`tests/test_windows_delivery.py` 已在该 ZIP 生成后修订。本审查逐项比较打包器当前选出的 330 个源文件/Skill/插件/记忆/vendor 文件，全部在候选内，且仅这两份文件摘要不同。此状态已被实施交接明确披露，不是隐瞒的规格偏离，但此候选不能作为最终源码一致包交付。

完成上述最小修订后，应生成新的单一输出目录与 ZIP/SHA/中文说明，重新逐文件校验、清洁解压、恢复全部核心表逻辑摘要及全部内层载荷哈希，并重跑包内离线检查。保留现有候选与失败证据；原生 Windows 验收继续待 Task 5，不能据 Mac 合成测试改成已通过。

## 本轮独立确认通过的范围

- `build_windows_delivery.py` 复用 `export_library`、`verify_archive` 和安装器 `allowed_payload`/`verify_bundle`；恢复证据复用 `restore_library`。输出使用新临时目录，ZIP 使用独占创建，没有覆盖旧交付或调用原发行脚本。复制前后及发布前核对源摘要。
- 安装器增量白名单仅为三份指定测试资产和 `runtime/wheels-dev/*.whl`，没有放开整个 upstream/config。候选实际未包含 session.json、cookies、profile、.env、behavior/runs 或 local-machine.json 路径。
- 独立重新计算了候选 ZIP 摘要和外层全部 451 个载荷的 size/SHA-256，全部一致，manifest 另占一个 ZIP 成员。插件 `.mcp.json` 在内，声明数量与实际数量一致。
- 对候选内层公开库重新调用 `verify_archive`，对已有清洁中文含空格恢复目录重新计算全部 590 个内层载荷的摘要与全部核心表逻辑摘要，均与内层 manifest 一致。数据库为 versions 49、search_index 49、provenance 49、audit 100、published 0、withdrawn 0；镜像为 2190 版本和 77809 文本单元。没有通过更改恢复内容来修正校验结果。
- 检查了实际恢复验证脚本中的旧目录 audit hook、双环境来源和逐来源卡断言，及 `task4-final-restoration.json`。实施方记录的 619 总计、607 通过、12 skip 仅属于 Mac host；最初引用卡 harness 错用不存在的模块全局变量后补跑的过程被保留，没有倒写为首次通过。本审查没有再次宣称执行这 619 项，也没有把新建 Mac 环境等同 Windows 锁原生运行。
- 当前 `tests/test_windows_delivery.py` 的 9 项合成边界测试在阻断 socket/connect_ex 和 Fetcher.get 下通过。首次直接运行因项目默认 `.venv-mcp1` 未装 dotenv 得到 1 error，随后显式选择本轮清洁恢复建立的 SDK1 site-packages 重跑，9 项全部通过；未安装或修改任何依赖。该环境设置是测试前提，首次失败保留于审查工具输出。
- 持衡 Windows Skill 与插件内嵌 Skill 的 24 个文件逐摘要一致。与原项目持衡目录逐文件 diff 仅有 Windows 入口、历史 Mac 覆盖注释、模拟法庭页 Windows 交叉链接和新增 windows-local.md；原法律分析、事实状态、自认、审批、来源、审计及工作流正文均保留。
- `memory` 仅有本项目 Index.md 和 Summary.md。组件来源说明包含官方运行时、锁定依赖、两个外部客户端、浏览器、Skill 和 china-law 历史许可差异；许可缺口没有被伪装为公开再分发授权。指南保留国家库 blocked、案例本人隐藏输入及当前宿主认证/检索/正文三步、独立 SDK、专用浏览器与 pending 边界，没有声称全国完整或本机 localhost 等于云端 GPT。

## 范围与简化审查

未发现需要删除的新抽象或重复实现。打包器直接复用既有数据迁移和安装校验，跨平台修复应集中于上述测试夹具和明确平台断言，不应新增第二套安装或权限框架。Ponytail：net: -0 lines possible。

本轮按 Obsidian 预检手动读取极小全局核心、注册项和当前项目小笔记，未收到记忆钩子输出。报告文字按 Humanizer 保留技术证据与限制，未改事实或引用。
