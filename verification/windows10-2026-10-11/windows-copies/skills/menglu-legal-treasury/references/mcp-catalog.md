# Windows 迁移组件

本包用于个人非商业学习。legal-tools 的两个客户端保留 CC BY-NC 4.0 许可和署名；改变用途时重新核对，不推定商业部署或公开再分发授权。安装根以[本机配置](configuration.md)的 state.json 为准。

| 组件 | 包内位置或入口 | 当前状态 |
| --- | --- | --- |
| 萌律共享法律检索，兼容名 chiheng-legal | target/legal_mcp.py，主环境 | 安装后依分项诊断和宿主实测确认 |
| 国家法律法规数据库 flk-npc | target/scripts/windows_flk_blocked.py | 保留 blocked，不绕过 |
| 人民法院案例库 rmfyalk | target/windows_case_access.py，独立 MCP 1 环境 | 需新机本地认证及当前宿主三步核验 |
| china-law 辅助材料 | target/vendor/treasury/sources/china-law | 仅必要索引/搜索脚本、JSON、README，非完整工作流 |
| bb-browser | target/windows_browser.py | 本人正常新登录，依赖冻结锁联网重建，Win10 待实测 |

元典、北大法宝、天眼查、Agentic China Lawyer、Claude for Legal HoriZon 和 Law Crawler RPA RAG MCP 未随包安装，不能根据旧 Mac 目录推定存在。获得授权并确认连接后，专业/企业数据源可用于相应任务；工作流模板不是权威法律依据。

官方法规和法院案例仍优先用于核验。封锁或不可用时保留待核状态。离线数量以 public_corpus_inventory() 或新导出清单为准，镜像保留 unverified_mirror。SQLite quarantine 不阻止检索，引用时展示来源卡、原文及缺失字段。全国覆盖、目标机上线与云端连接均未验收。
