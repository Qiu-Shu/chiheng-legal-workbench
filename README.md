# 持衡法律工作台

个人非商业学习项目：共享公开法源检索、诉讼文书攻防审查，以及个人本机民商事一审模拟法庭。多个律师助手 Skill 可以复用同一法库服务。

这是 **2026-10-11 的工程续建快照，不是 Windows 10 正式发行版**。先读 [HANDOFF.md](HANDOFF.md)，再继续实施。现有来源覆盖有限，不代表全国法律完整数据库；任何真实引用仍须核对原文和来源。

## 从哪里接手

- [工程交接与下一步](HANDOFF.md)
- [Windows 原生迁移计划](docs/superpowers/plans/2026-10-09-windows10-migration.md)
- [尚未关闭的 Task 4 审查意见](verification/windows10-2026-10-11/task4-spec-review.md)
- [共享法库接口约定](docs/shared-library-contract.md)
- [模拟法庭使用说明](docs/personal-mock-hearing-guide.md)

根目录保留核心 Python 程序。`scripts/` 是安装、采集、更新、验证和打包入口，`tests/` 是测试与公开/合成夹具，`skills/`、`plugins/` 保留原 Mac 版源文件。Windows 专用副本位于 `verification/windows10-2026-10-11/windows-copies/`，不要覆盖 Mac 版。

代码仓库不携带公开法库数据库及原件、法规镜像索引、Python/Node 运行时、依赖包、案卷、登录凭据、浏览器资料或完整 Obsidian 库。克隆代码不等于完成安装或恢复数据。资料迁移和依赖恢复见交接文档。

## 第三方组件

保留各组件自己的 LICENSE、NOTICE 和 SOURCES.md。没有为整个仓库新增统一开源授权。外部组件的历史许可差异尚需核对；此仓库用于本人私有工程续建，不代表获准公开再分发。
