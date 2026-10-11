# 个人迁移副本来源

上游为 moyupeng0422 的 [legal-tools](https://github.com/moyupeng0422/legal-tools)，适用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)。总许可与原 README 保存在 `sources/legal-tools/`。本包仅用于用户本人的非商业学习迁移，未增加公开或商业部署许可。

2026-10-11 从当前个人 Treasury 的 `sources/legal-tools` 逐文件复制国家库、案例库各六个脚本、requirements、README 和对应 API 参考，以及总 LICENSE、README。实际清单见本包的 manifest。没有复制 `.env`、`.python-deps`、日志、浏览器数据或凭据。

只修改案例库 `scripts/client.py`：在任何启动读取之前，把默认认证路径指向本安装 `windows_case_access.access_path()`；Windows 打开分支使用 `windows_private.open_file(private=True)`，沿用有界读取和原有认证恢复逻辑。原文件 SHA-256 为 `2c2e315f1a0c11de153b0776bea374a2f36048a96ebd63fee8a782aaf0d57199`，副本 SHA-256 为 `01333afff14f0bb542c1d80a504f84c125a9a5e83f99b61a51ac061a93e0b17c`。

源码 README 中的旧环境变量、`.env`、原机器路径和原安装指令仅为上游资料。Windows 操作以 `docs/windows-external-setup.md` 为准。国家库新入口始终返回 `FLK_ACCESS_BLOCK`，保存源码不表示恢复自动访问。
