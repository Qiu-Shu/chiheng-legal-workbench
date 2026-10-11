# Task 3B 独立代码质量审查

2026-10-11。结论：CHANGES_REQUIRED。发现一项 P2 状态保护缺陷，需在本轮修复。Windows 原生验收仍待 Task 5，不是此结论的原因。

## Strengths

- 外部 SDK 使用独立 `.venv-mcp1`，固定 MCP 1.28.0，并实际导入 FastMCP 检查。主 SDK2 安装未被替换。Python、Node、pnpm 的本地归档哈希均与固定常量一致，依赖安装使用哈希锁或冻结锁，bb 安装后核对补丁身份。
- 案例 client 在模块启动读取前选定本安装 `private/case-access.env`，Windows 读取复用已审查的私有文件句柄；保存采用隐藏输入和原子替换，失败保留旧文件。认证值存在仍报 pending，原有账号、检索、对应正文三步及换证复核保留。
- 受控浏览器入口在子进程前拒绝 OpenClaw、日常历史推荐与未迁移更新路由；固定 CDP、新 profile、进程创建时间及监听归属检查覆盖日常顺序调用。明确连接失败、未知状态和超时均不回退日常浏览器。
- 核心成功与外部未验状态分开；国家库入口继续使用 FLK_ACCESS_BLOCK；宿主只生成连接片段并检查同名项。文档没有把本机合成检查写成 Windows、账号或宿主接入成功。

## Issues

### 1. [P2] 拒绝已有 daemon 状态后，外层错误处理仍删除该文件

位置：`vendor/bb-browser/package/dist/daemon.js:11124`，关联 `:10955`、`:10878`；可达窗口在 `windows_browser.py:251` 到 `:257`。

Windows 的 `cleanupStaleDaemon()` 检测到既有 `daemon.json` 后抛出错误，符合不接管未知状态的要求。但 `main().catch(...)` 随即无条件调用 `cleanupDaemonJson()`，后者只检查文件存在便删除。这个 daemon 从未登记该状态，拒绝后却清除了其他实例的连接记录。

受控入口也存在可达的并发场景：两个首次调用都在 `check_daemon()` 和 `port_free(19824)` 处看到空闲，随后同时进入 CLI 的首次启动。一个 daemon 先创建状态，另一个启动较慢的 daemon 在 `cleanupStaleDaemon()` 看到该文件并拒绝，然后被外层 catch 删除先启动实例的记录。即使两者都先通过状态检查，后启动者在 HTTP 端口绑定失败时也进入同一个无条件删除分支。

这不会结束浏览器或未知 PID，但会丢失仍在运行实例的连接信息，使后续调用因陈旧 owner 或占用端口停止，并破坏了要求保留的人工核查现场。普通串行调用的前置检查能挡住既有状态；当前代码没有将检查和启动串行化，因此不能消除上述窗口。

独立离线复现使用实际 `cleanupDaemonJson`、`cleanupStaleDaemon`、`main` 及文件末尾 catch，文件与进程操作全由记录器代替。输出为：

```json
[["fatal"],["deleted","SYNTHETIC/private/bb-state/daemon.json"],["exit",1]]
```

最小修复：Windows 启动失败时保留已有状态，或者只清理由本进程成功登记且身份仍匹配的状态。无需增加自动恢复或进程管理器。补丁身份常量、来源说明与哈希清单应同步；补充覆盖完整 `main().catch(...)` 的离线回归，断言既有未知状态和竞争实例留下的状态均不被删除。现有 JS 测试只调用 `cleanupStaleDaemon()` 并断言拒绝，没有执行外层 catch，因此未覆盖这条清理路径。

复现代码，可从项目根目录交给已知 Node 的 `--input-type=module` 标准输入执行：

```javascript
import fs from 'node:fs';
const text = fs.readFileSync('vendor/bb-browser/package/dist/daemon.js', 'utf8');
const cleanup = text.slice(text.indexOf('function cleanupDaemonJson() {'),
  text.indexOf('async function discoverCdpPort(host, port) {'));
const main = text.slice(text.indexOf('async function cleanupStaleDaemon() {'),
  text.indexOf('//# sourceMappingURL=daemon.js.map'));
const effects = [];
const run = new Function('process', 'existsSync4', 'unlinkSync2', 'DAEMON_JSON',
  'parseOptions', 'console', cleanup + main.replace('main().catch', 'return main().catch'));
await run({platform: 'win32', exit: code => effects.push(['exit', code])},
  () => true, path => effects.push(['deleted', path]),
  'SYNTHETIC/private/bb-state/daemon.json', () => ({}),
  {error: () => effects.push(['fatal'])});
console.log(JSON.stringify(effects));
```

未发现其他需要本 Task 增加工作的 P0、P1、P2 或 P3 问题。Ponytail-review 未发现独立的过度设计；不建议为风格重写现有适配器。net: -0 lines possible.

## Assessment

CHANGES_REQUIRED。修复上述错误清理并通过完整错误链的离线回归后，可再次评定本 Task 的代码质量。剩余原生 Windows、本人登录、浏览器实际启动与宿主导入保持 pending；无需为了通过本次质量审查伪造或提前完成这些验收。

本次独立执行：

- 项目 `.venv/bin/python -B`，拦截 socket 的 `connect`、`connect_ex`，运行 `test_windows_external.py`：25 项，23 通过、2 个 Windows ACL 原生检查跳过。
- 已知本机 Node 运行 `tests/windows_bb_boundary.mjs`：8 项通过。该脚本执行实际副本函数，全部副作用使用替身。
- 上述完整 daemon 错误链探针：稳定复现拒绝后删除合成状态。没有运行真实 daemon 或删除任何真实文件。
- 重新计算固定 Python 3.13.16、Node 22.23.3、pnpm 11.25.0 归档哈希，均匹配实现常量。未联网重新获取官方元数据，也未执行 Windows 二进制。
- `task3b-review-after.sha256` 的 7 个文件逐项核对通过；当前 CLI 哈希 `3f496cf5b832ae3e83246d87da82617060d2491f041b773b1ab4360d5bc5fc5d`，daemon 哈希 `34e83e7b63e007afd0126e1cfd5331c81034d80908d9df1e93adb554dc6fd7f7`。以 `task3b-before/`、vendor provenance 原件及当前哈希作为非 Git 的前后依据，没有 init 或 commit。

本次未独立重跑实现者报告的 610 项全量，也未重跑旧案例恢复 48 项。Task 4 打包、Skill 副本和旧测试便携路径不作为本轮阻断；Task 1、Task 2、Task 3A 的已审查基础仅核对集成调用。审查未读取真实 `.env`、浏览器 profile 或账号配置，未连接账号、改服务或主库；唯一新增文件是本报告。

使用 requesting-code-review 的正确性与安全审查结构、Ponytail-review 的最小实现检查；Humanizer 仅整理报告文字，没有改变技术结论。记忆钩子未提供实际输出，本次已手动读取全局核心和匹配项目的索引、摘要、最近更新。

## 修复复核，2026-10-11

最终质量结论：PASS。首轮唯一 P2 已关闭；上方首轮结论与复现证据保留。本结论限 Task 3B 代码质量与离线合成检查，原生 Windows、真实登录、浏览器实际操作及宿主导入仍 pending。

复核实际改动：`vendor/bb-browser/package/dist/daemon.js:10880` 在公共 `cleanupDaemonJson()` 的 Windows 分支立即返回。相较修复前副本，daemon 只增加这一条件和说明注释。拒绝已有状态、端口竞争失败、正常 shutdown 都经过同一保护；Windows 不再探测或删除状态文件，退出过程中被其他实例替换的文件也保留。CLI 的 stale 分支和 `stopDaemon()` 仍先拒绝 Windows 清理，无新增自动恢复管理逻辑。

该方案会在正常退出后保留自身状态，下一次启动仍需人工复核。`docs/windows-external-setup.md:60` 和 `vendor/bb-browser/SOURCES.md:17` 已明确说明这一限制、保留现场及不能假定自动重启，符合本轮批准范围。

本次独立执行与核对：

- Node 重新运行更新后的 `tests/windows_bb_boundary.mjs`，12 项全通过；先读过测试实现，确认执行了真实 `main`、外层 catch、CLI stop/stale 和 shutdown 函数。临时合成文件的完整字节保持断言覆盖已有外来状态、两次 main 并发竞争、正常退出保留自身状态，以及退出等待期间被替换的状态。没有真实网络或子进程。
- 另用首轮独立探针分别执行修复前与当前副本：修复前仍输出 `fatal/deleted/exit(1)`，当前仅输出 `fatal/exit(1)`。额外直接执行实际公共清理函数，Windows 分支的文件探测及删除调用均为零；合成 darwin 分支仍执行原有存在检查与删除，说明非 Windows 行为未被本次条件改变。
- 项目 `.venv/bin/python -B` 在 socket.connect/connect_ex 禁用下重跑外部专项：25 项，23 通过、2 个 Windows ACL 原生检查跳过；实际 `verify_source()` 通过。
- `task3b-quality-after.sha256` 的 5 个文件、总体 `task3b-after.sha256` 和 `task3b-vendor-after.sha256` 均逐项核对通过。当前 daemon 哈希为 `22c9ebbf57ff69be90b1491d6a7e2622968755d4c7d00531504961cd8078bb10`，与 wrapper 常量、来源说明一致；CLI 哈希保持 `3f496cf5b832ae3e83246d87da82617060d2491f041b773b1ab4360d5bc5fc5d`。

未新增其他重要质量问题。Ponytail-review 复核确认修复集中在现有公共清理入口，无需新增抽象，净可删冗余仍为 0 行。未独立重跑实现者报告的 610 项全量；本次只追加本报告，未修改实现、凭据、浏览器 profile、服务或主库。
