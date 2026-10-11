# 组件来源与个人迁移范围

交付目标：用户已有个人非商业学习环境的 Windows 10 x64 副本。总包外层 manifest 逐文件记录长度和 SHA-256；内层公开资料 ZIP 独立保留数据库逻辑摘要、全部载荷摘要、来源和审核状态。版本以锁文件及文件内元数据为准。

| 组件 | 来源与版本 | 许可与边界 |
| --- | --- | --- |
| 持衡 Skill 与插件 | 本项目当前版本；Windows 副本仅更改平台入口/说明，插件身份保留 | 各副本 LICENSE、NOTICE，保留原作者署名；未上传账号 |
| 萌律法律宝典 Skill | 用户当前已安装的 5 文件副本，Windows 配置/目录说明适配 | 个人已有指令迁移，没有新增第三方工作流的分发许可推定 |
| Scrapling 官方 Skill | 已安装的 scrapling-official 0.4.15；[官方项目](https://github.com/D4Vinci/Scrapling) | Skill 内 LICENSE.txt 和元数据；上游反爬示例不能覆盖本项目来源许可、robots 与封锁边界 |
| Python / Node / pnpm | Python 3.13.16 x64、Node 22.23.3 x64、pnpm 11.25.0，官方链接及 SHA 见 runtime-sources.md | 运行时原包自带许可证；仅下载与核对，未因此宣称 Windows 已运行 |
| 主环境与外部 MCP1 | requirements-windows.lock.txt / requirements-windows-mcp1.lock.txt，PyPI 各 wheel 与哈希 | wheel 内 LICENSE/METADATA；MCP2 与 MCP1.28.0 隔离 |
| 可选测试依赖 | [ReportLab 4.4.9](https://pypi.org/project/reportlab/4.4.9/)，SHA 68e2d103ae8041a37714e8896ec9b79a1c1e911d68c3bd2ea17546568cf17bfd | wheel 内 BSD 许可，依赖 Pillow 与 charset-normalizer 已在主锁；非核心启动前提 |
| legal-tools 两客户端 | [moyupeng0422/legal-tools](https://github.com/moyupeng0422/legal-tools)，来源见 vendor/treasury/SOURCES.md | CC BY-NC 4.0，原 README/LICENSE 保留；国家库入口仍 blocked |
| bb-browser | [epiral/bb-browser](https://github.com/epiral/bb-browser) 0.14.2，来源/补丁见 vendor/bb-browser/SOURCES.md | MIT，有限溯源原件保留；无 node_modules、profile 或凭据；目标冻结联网重建 |
| china-law 辅助副本 | 用户已有 Treasury 中的 build_index.py、search.py、README 和三个必要 JSON | 本地 README 的 MIT 徽章与现上游根 Apache-2.0 不一致，未找到对应历史许可；仅个人原副本迁移，不声称公开再分发许可完成 |
| 公开法源与镜像 | 来源卡、原件及索引随内层资料包保存，context 中保留观察到的许可/来源文件 | 不把官方公开网页等同于批量使用许可；镜像为 unverified_mirror |

没有迁移私人案卷、模拟会话、真实认证值、浏览器登录、旧 Mac 环境、全 vault 或全局配置。源码历史文档、上游 README 和有限溯源文件可能保留旧路径作为历史证据；Windows 运行一律使用实际 target 和 Windows 说明，不执行历史安装路线。
