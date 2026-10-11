# bb-browser Windows 候选副本

程序为 [epiral/bb-browser](https://github.com/epiral/bb-browser) 0.14.2，MIT 许可保存在 `package/LICENSE`。从当前本机 0.14.2 安装逐项复制根 package.json、冻结 pnpm-lock.yaml，以及实际 npm 包的 package.json、dist、web、packages/shared/buildDomTree.js、README、LICENSE。未复制 Mac node_modules。

`provenance/` 保存原 Mac 边界补丁、原件与检查记录，仅供溯源；里面的 Mac 路径和 shell 入口不在 Windows 执行。dist 的 `.map` 保留上游源映射，以下最小修改以实际 `.js` 为准，源映射未重新生成。

`provenance/daemon.input.js` 是上述白名单 dist/daemon.js 的补丁前副本，用于来源核对及合成安装测试；`task3b-input.sha256` 记录全部 vendor 输入文件的哈希。

| 文件 | 输入 SHA-256 | Windows 副本 SHA-256 |
| --- | --- | --- |
| dist/cli.js | 2cfb269144ba54c10359c33a4c2816136cefeeb3f19ea7e57443877252352dee | 3f496cf5b832ae3e83246d87da82617060d2491f041b773b1ab4360d5bc5fc5d |
| dist/daemon.js | f1060b67efe59f5669604ef0b2f5ce1bab93470e0555875c4b90f16aa1e0014e | 22c9ebbf57ff69be90b1491d6a7e2622968755d4c7d00531504961cd8078bb10 |
| pnpm-lock.yaml | 36ebe4a184964d23d6857dff3719a04b6043f4fd9d012685213fe8327df44314 | 未修改 |

CLI 保留显式 CDP 连接失败即停止的既有补丁，新增 `--no-chrome` 启动参数和 Windows 旧状态拒绝。daemon 的 Windows 分支仅接受 `127.0.0.1:19224`，连接失败不回退 managed port；发现已有 daemon.json 就拒绝，不清理或结束记录中的 PID。

Windows 的公共 `cleanupDaemonJson` 直接保留文件，覆盖启动拒绝的外层 catch、HTTP 端口竞争失败、正常退出及退出期间被替换的状态；不尝试读后删除或判断未知进程归属。正常退出也会留下状态，后续重启需要人工核对，不提供自动清理。遇到阻断应保留状态文件及 profile 供复核，不能仅凭报错删除。

独立规格审查后，CLI 与 daemon 的 site 根目录均改为优先使用本安装 `BB_BROWSER_HOME`，Windows 的普通 site 命令不再触发隐式 `silentUpdate`。Windows wrapper 拒绝 `--openclaw`、实际历史入口 `site recommend`、尚未迁移的 `site update`，同时保留固定 CDP 的核心命令及 site 读取/执行；所有 CLI 调用限 120 秒。源映射与溯源副本保留原文，不能代替当前受控入口执行。

目标机使用随包 Node 22.23.3、pnpm 11.25.0，通过冻结锁和 `--ignore-scripts --prod` 联网取得依赖。安装器先核对新下载上游 CLI `72e9ec031a5fdf272d091d561b85a4a9a39aec8c7e0d458429cdc7ed8b506f59` 及 daemon 输入身份，再覆盖本安装新建依赖目录里的两个补丁文件。每次通过 Windows wrapper 调用均重新核对补丁 SHA-256。外部当前 Mac 安装不受修改。

本副本尚未在 Windows 10 执行。`site recommend` 的日常浏览器历史/Unix sqlite3 路线和 `site update` 的旧 shell 更新路线在 wrapper 明确拒绝；其他命令同样需目标机逐项确认。Playwright/Patchright 1.63 官方当前要求 Windows 11+，本包保留依赖与源码，不把 Windows 10 浏览器自动化标为已通过。
