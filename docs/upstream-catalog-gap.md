# 上游法规目录与本地索引差集

核验时间：2026-09-27。用途：个人非商业学习。这里只核对公共法规目录 ID，不下载整个原文库，不判断法条当前有效性，也不把目录命中视为正文验收。

## 结果

| 项目 | 实测数量 |
|---|---:|
| lawtext 全国卷目录记录 / 唯一 ID | 2,508 / 2,508 |
| 既有本地索引记录 / 唯一 ID | 2,190 / 2,190 |
| 两者共有 ID | 2,190 |
| 上游有、本地没有的 ID | 318 |
| 本地有、上游没有的 ID | 0 |

本地 `law-index.json` 文件名中的 ID 与 `provision-index.json` 的键集合完全相同。差集按 `bbbs` / 法规 ID 精确比较，没有按标题合并，也没有假设同名文件属于同一版本。

这 **318 条是待核查目录缺口**。不能称为“已下载的新增法规”“已补齐的全文”或“318 条现行有效法规”。本次没有把它们发布入正式可引用库。

### 缺口类别

| 上游原始类别 | 数量 |
|---|---:|
| 司法解释 | 164 |
| 行政法规 | 116 |
| 法律 | 28 |
| 修改、废止的决定 | 5 |
| 有关法律问题和重大问题的决定（部分） | 3 |
| 法律解释 | 2 |

## 固定版本与完整性

上游是作者维护的 [lawtext/law-flk-vol1](https://github.com/lawtext/law-flk-vol1)，是官方来源的社区镜像，不是全国人大官方软件仓库。本次固定到 [提交 f1f75a6b3248a87ddc9e888708f9b1de56fff9c4](https://github.com/lawtext/law-flk-vol1/commit/f1f75a6b3248a87ddc9e888708f9b1de56fff9c4)，提交时间 `2026-09-26T12:33:03Z`。

下载对象只有 `records.json`、`LOG.md`、GitHub 提交/根目录/文件对象证据；该提交根目录没有 README，因此没有编造 README 文件。原始下载端点连续超时后，改用同一提交指向的 Git Blob API，解码得到相同对象。

| 原文件 | 字节 | SHA-256 |
|---|---:|---|
| records.json | 1,547,013 | `fef5c0ff0a75fc44969eb4dcc25ac49fc1c979e92064da3390fef3e74144a908` |
| LOG.md | 178 | `6aff6abc1001e8d915d67d5d07365c27e9696c92ce65638074e56671e31838d2` |

两个文件同时通过 Git blob SHA-1 与根目录对象信息的校验，验证下载完整且对应固定提交。全部输出及本地输入的 SHA-256 记录在 [manifest.json](/Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review/data/upstream-catalog/lawtext-2026-09-27/manifest.json)；哈希校验不证明文本法律效力或内容正确性。

本地输入 `provision-index.json` 为 41,060,097 字节，SHA-256 为 `26acddc182e4ecaca66dc48380cd590b8c1a9c2cca177a652bcad01fa78e45ad`。生成的本地对照快照只保留 ID 与法规元数据，不复制 `provisions` 正文。

## 上游目录的实际限制

`records.json` 自报更新时间标签 `20260926T20+0800`，统计为 `total=2508`、`download=175`、`error=2333`、`new=39`。这些是镜像维护程序的原始字段，不应改写成成功全文数量或法律有效状态。

318 个缺口中，`my_status=200` 有 42 条，`my_status=404` 有 276 条。这说明即使发现了目录条目，也不能据此承诺能取得对应文件。本报告不进一步推断这些抓取状态码的原因。

缺口的原始 `sxx` 值为：`1` 249 条、`2` 2 条、`3` 51 条、`4` 8 条、空值 8 条。本次保留原值，没有脱离官方字段定义和单篇核验自行翻译为“现行有效”。

`LOG.md` 记录《农产品质量安全法》2018 版与 2006 版文件相同、实际缺少 2018 版。该异常已随目录保存，不能在后续导入时遗失。

## 可复查交付物

- [差集 CSV](/Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review/data/upstream-catalog/lawtext-2026-09-27/catalog-gap.csv)：318 条元数据，保留原始状态；UTF-8 BOM，便于表格软件打开。
- [差集 JSON](/Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review/data/upstream-catalog/lawtext-2026-09-27/catalog-gap.json)：包含上游原始记录、共同 ID 和本地独有列表。
- [计数摘要](/Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review/data/upstream-catalog/lawtext-2026-09-27/gap-summary.json)：集合计数、类别和原始状态分布。
- [固定目录原件](/Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review/data/upstream-catalog/lawtext-2026-09-27/records.json)、[上游异常记录](/Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review/data/upstream-catalog/lawtext-2026-09-27/LOG.md)。
- [本次复查脚本](/Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review/data/upstream-catalog/lawtext-2026-09-27/audit_catalog.py)：只比较已下载的公共元数据，能重算差集并检查 Git blob、SHA-256；不联网，不执行上游代码。

JSON 中的 `official_url` 由官方 ID 构造，并显式标注未打开核验；该链接存在于输出不代表此轮已访问官方原文。

## 后续自动目录检查

[refresh_upstream_catalog.py](/Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review/scripts/refresh_upstream_catalog.py) 提供独立可复跑入口：

```sh
.venv/bin/python scripts/refresh_upstream_catalog.py \
  --config config/shared-library.json \
  --output-root data/upstream-catalog
```

应在项目根目录执行；参数也支持绝对路径。它读取配置中的本地公共法源索引，先取得 GitHub 当前提交，再只从该固定提交下载目录、异常记录以及存在的 README。程序校验非空、记录结构、唯一 ID、总数及 Git blob 完整性；成功后保存新快照、SHA-256 清单及差集，最后原子更新 `latest.json`。旧快照保留。

同一提交和同一本地索引再次运行时返回 `unchanged`；上游提交变化时记录新增和移除的目录 ID；本地索引改变时重新计算差集。首次建立基线不把 2,508 条都误报成“刚新增”。下载失败、空目录、重复 ID 或哈希不符时退出 1，保留最后良好快照；成功退出 0。脚本不会下载目录关联的 DOCX 或调用上游程序。

已添加并通过 4 项定向测试，覆盖精确差集与哈希、远端异常保留旧数据、新提交增量、同提交下本地索引变化。测试只使用模拟网络边界和临时目录，不调用生产接口或写入法规正文库。

2026-09-27 07:58 UTC 已完成真实联网刷新，退出码为 0，结果与固定快照审计一致：上游 2,508、本地 2,190、差集 318。当前 [latest.json](/Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review/data/upstream-catalog/latest.json) 指向 `snapshots/f1f75a6b3248a87ddc9e888708f9b1de56fff9c4-26acddc182e4`。

首次使用 Python 原生下载时遇到 TLS EOF，刷新未覆盖旧数据；实际使用的版本改用本机 `/usr/bin/curl`，继续验证 HTTPS 证书，并以参数列表调用，未使用 shell 执行下载内容。下载范围仍是目录文件。

最终边界：最新目录不等于最新正文，不等于已经生效，也不等于本地已核验覆盖。正式引用仍需回到具体官方原件核对版本、条文和适用时间。
