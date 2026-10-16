# Windows 原生私有文件接口修复

基线：e09e47fa4a93763cb50c0b8df3004bb10200cde1；本地分支 codex/windows-native-continuation。

首次隔离安装核心 doctor 失败，未激活服务或写入全局 MCP 配置。Windows 10 AMD64，安装包恢复的 Python 3.13.16、pywin32 312。其 `win32con` 不包含 `FILE_FLAG_OPEN_REPARSE_POINT`，该常量实际由 `win32file` 导出，值 0x00200000。没有依赖模块被同名源码遮蔽。

## 修改

`windows_private.py` 改从 win32file 取上述常量；三个策略测试的模拟模块相应纠正。无新增依赖。不改变无删除共享、祖先句柄保持、重解析点与硬链接拒绝、同句柄对象/ACL验证及失败关闭。

## 实测

使用失败安装生成的独立解释器，在当前源码目录执行；不修改旧恢复包或失败安装源码。

| 命令（共同前缀 python -B -X utf8） | 结果 | 退出码 |
|---|---|---|
| 修复前 -m unittest tests.test_windows_private.WindowsPrivateNativeTests -v | 8项错误，均在缺失常量处失败 | 1 |
| 修复后 -m unittest tests.test_windows_private -v | 14通过，含8项真实Windows原生及合成完整演练；0跳过 | 0 |
| -m unittest tests.test_windows_portability -v | 10通过、1个POSIX flock专属跳过；实际Windows跨进程锁通过 | 0 |
| git diff --check | 无错误 | 0 |

原始本机日志分别保存在仓库父目录 native-source-red.log、native-source-after-constant.log、windows-portability-first.log；首次失败安装日志为 chiheng-install-01.log。

独立双轴审查分别重新核验常量归属并运行14项私有文件测试，均退出0、无跳过。Standards 0项发现；Spec 0项发现。结论仅覆盖上述两文件差异。

完整离线回归、可移植夹具修复、新候选制作、新安装验收、宿主连接和自启动仍待实施。本报告不把原生接口修复等同于持衡整体完成，不涉及真实私案或法律效力核验。

## 一手依据

- https://github.com/mhammond/pywin32/blob/main/win32/src/win32file.i
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilea
- 当前隔离环境实际导入模块与锁定版本，以及上述测试实际执行输出。
