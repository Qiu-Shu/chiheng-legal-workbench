# bb-browser 0.14.2 本机边界补丁

2026-10-09，按授权仅修改固定安装入口与 CLI 的显式 CDP 地址失败行为。原 npm 安装的 CLI 字节已在修改前复制为 `cli.original.js`，原本机入口保存为 `bb-browser.original`。安装版本号仍是 0.14.2，但当前 CLI 带本机补丁，不再与 npm 包内文件逐字节相同。pnpm-lock.yaml 中的 integrity 标识下载包，不证明修改后的 CLI 字节。

## 修改

- wrapper 使用参数数量与首参共同判断，只有单独的 `--help`、`-h`、`--version` 或 `-v` 允许跳过专用浏览器检查。
- `discoverCdpPort()` 在显式 `BB_BROWSER_CDP_URL` 解析失败、没有有效端口或连接不可达时抛错，停止自动发现其他浏览器。没有设置该环境变量时，上游原有行为保留；正常可达地址继续直接返回。
- 补丁只有上述分支修改；apply_patch 同时为原 CLI 文件末尾补上换行。未修改 daemon、安装说明、锁文件或其他安装。

修改前两个文件硬链接数均为 1：wrapper inode 9165728，CLI inode 9148766。CLI 不是与其他安装共享的硬链接，没有修改全局 pnpm 存储。

## SHA-256

| 文件 | 原件 | 修改后 |
|---|---|---|
| `/Users/songmenglvshi/.local/bin/bb-browser` | `5947af45d0c5befdce1568c39a70a15cabcfb4ba086f19b9e5d5e34191af90ff` | `db7d718e3e0bee7e50c0fd411a5f9126f71722e5db5371e49c8e0ed0b8968e77` |
| `/Users/songmenglvshi/.local/share/bb-browser/0.14.2/node_modules/bb-browser/dist/cli.js` | `72e9ec031a5fdf272d091d561b85a4a9a39aec8c7e0d458429cdc7ed8b506f59` | `2cfb269144ba54c10359c33a4c2816136cefeeb3f19ea7e57443877252352dee` |

备份文件的 SHA-256 与上表原件列一致。未重新下载 npm 包；原件指本轮修改前已安装的文件。

## 验证

遵循 TDD，先建立 `boundary-check.mjs` 并对正式文件运行，得到 8 通过、7 失败，退出码 1；记录见 `red-before-patch.txt`。修复后同一脚本 15 通过、0 失败，退出码 0。随后通过 `--original` 读取保留原件重跑，仍为 8 通过、7 失败，退出码 1。

失败项覆盖多参数帮助/版本查询豁免与三类显式地址失败。版本多参数测试验证新增参数数量约束，本身不表示上游原版版本查询会启动浏览器。成功项覆盖单参数帮助/版本查询、正常入口拒绝与放行、可达专用地址选择，以及未指定地址时的上游行为。

脚本提取实际文件中的 `discoverCdpPort()` 执行，替换连接与参数依赖；wrapper 则保留实际 shell 分支，仅替换 curl 与最终 CLI 执行。测试没有网络、浏览器启动/停止或秘密状态读取。所有修改后的 shell/JavaScript 语法检查通过；本轮尚待另一位审查者独立复核。

重跑：

```sh
/Users/songmenglvshi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node /Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review/verification/bb-browser-2026-10-09/boundary-check.mjs
# 预期 15 通过，退出码 0
/Users/songmenglvshi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node /Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review/verification/bb-browser-2026-10-09/boundary-check.mjs --original
# 预期 7 失败，退出码 1；用于核验原缺陷，勿当成当前安装测试失败。
```

重新安装或升级可能覆盖本机补丁，届时应重跑检查。当前补丁只处理本轮发现的两个缺口；显式调用原始 daemon 等其他入口不受本 wrapper 限制。最初审查记录 `review.md` 保留作为修复前证据，本文件说明修复状态。
