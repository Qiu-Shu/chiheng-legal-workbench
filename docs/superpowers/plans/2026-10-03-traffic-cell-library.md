# 交通裁量附件逐格定位入库实施计划

> **For agentic workers:** Use subagent-driven-development逐项实施，每项先规格复核再质量复核。用户已确认设计及持续实施，不在任务之间反复询问。项目非Git仓库，不创建工作树或伪造提交。

**Goal:** 将本批交通通知、规则及八表按原件和单元格可追溯地纳入共享法库，保留不同来源版本及未完成项。

**Architecture:** 原始文件只读，固定来源集合清单保存父子关系；工作簿读取与检索正文投影分离；复用现有SQLite、只读MCP和迁移机制。先离线全量核查，再实际入库，不放宽现有解析器。

**Tech Stack:** Python 3.12、unittest、openpyxl、xlrd、既有lxml/Scrapling/SQLite。依赖限定项目环境。

## 任务1：只读工作簿结构与可追溯投影

状态：2026-10-03完成本项受限读取实现，35项专项通过；后续集成发现并修复富文本字体名称的JSON归档问题，独立规格、质量复核均再次通过。最初红灯及复核修复史保留于 `verification/traffic-workbooks-2026-10-03/`、`verification/traffic-workbooks-spec-review-2026-10-03.md` 和 `verification/traffic-workbooks-quality-review-2026-10-03.md`。五份XLS、新建设来源XLSX仍按未支持门禁拒绝投影，不代表八表全部已入库。

文件：新增 `traffic_workbooks.py`、`tests/test_traffic_workbooks.py`；必要时按明确职责分出 `traffic_workbook_cells.py`（读取与显示逻辑，不建立通用Excel框架）。依赖追加到 `requirements.txt`。

接口：`read_workbook(payload: bytes, suffix: str) -> dict` 返回原件哈希、所有工作表、非空单元格、原值/类型/数字格式、富文本片段/字体语义、合并范围、隐藏/对象/页眉页脚等观察结果及未支持项。`project_workbook(snapshot: dict) -> tuple[str, list[dict]]` 返回带坐标和合并锚点的可检索正文及定位索引；有未支持项时拒绝生成可入库正文。

- [x] 先创建真实文件测试，红灯必须来自功能缺失。运行 `.venv/bin/python -m unittest tests.test_traffic_workbooks -v`，将首次红灯输出保存在独立日期证据，不覆盖旧验收。
- [x] 单元格示例测试（实际fixture路径用已保存SHA文件）：

```python
snapshot = read_workbook(payload, '.xlsx')
assert len(snapshot['sheets']) == 2
assert snapshot['sheets'][1]['cells'] == {}
assert len(snapshot['sheets'][1]['merges']) == 2
text, locations = project_workbook(snapshot)
assert 'Sheet2' in text
assert 'A4' in text
```

- [x] 边界测试：非支持格式、损坏容器、公式、错误值、隐藏数据/隐藏表、对象/外链、合并区中未覆盖内容、普通空白不能继承、富文本删除线不能套用整个格、`0.00_ `展示编号不能退化、正文和坐标必须可回读，未知结构明确拒绝。人工构造测试文件只用于测试，不伪装成官方原件。
- [x] 复用成熟读取库，完整保留原值，不用数值编号作唯一键。XLS记录可用xlrd内置统计帮助诊断，但无公式不等于所有扩展结构安全。没有可靠读法的字段保留未支持，不臆断；可以先交付有明确门禁的结构读取，不能宣称全部八表已验收。
- [x] 测试通过后独立规格、再质量复核；问题回到原实现者修正再复验。审查范围包括内存/文件边界、依赖可移植性、无网络/数据库副作用。

## 任务2：固定来源集合、通知/规则和入库连接

状态：2026-10-03实现、规格复核及质量复核通过。26项集合专项，最终全量399项通过且主代理独立复跑确认；真实临时库22来源SHA匹配，6正文可用、6明确阻断，重复导入版本/来源/审计不增。真实HTTP服务及主库操作由任务3验收，不能用本项临时库结果替代。证据：`verification/traffic-collection-implementation-2026-10-03.json`、`verification/traffic-collection-cli-replay-2026-10-03.json`、同日规格和质量复核报告。

文件：新增 `traffic_collection.py`、`config/jilin-traffic.json`、`scripts/ingest_jilin_traffic.py`、`tests/test_traffic_collection.py`。仅必要时扩展共享来源卡展示或迁移配置白名单，并补对应测试；不修改现有HTML/PDF严格约束。

- [x] 先写失败测试：集合漏任一附件不可报告完成；规则及八表原件哈希必须命中清单；父网页附件名与内部名分别保存；两项跨源差异不能覆盖；重复导入不增版本或审计。
- [x] 清单的输入证据为 `verification/remaining-jilin-probe-20260928/network.json` 和 `verification/traffic-cross-source-2026-10-03/network.json`；附件身份依据父网页、标题、原件、内部标号联合核对，不按编号单独判断。
- [x] 通知先只读复核保存的HTML模板、附件清单及全文覆盖，再用专门入口解析。规则使用既有 `convert_legacy_doc`/`extract_docx` 双转换流程；不得忽略主DOCX的表格或冒称与HTML完全一致。
- [x] 入口签名 `ingest_collection(root, manifest, reader, store)`，逐份状态包含 `original_acquired`、`parsed`、`version_id`、`failure_reason`，最终 `complete` 仅在所有要求资料解析/存储回读成功时为真。失败可安全重放。
- [x] 入库使用 `LegalStore.add`，`law_id`包含通知集合与附件稳定身份，provenance保存父通知、来源、SHA、日期、定位、冲突和未审核状态。输出正文不冒充法条。相同字节不同来源保持两条来源证据；不同字节分别保存版本。
- [x] 原件/派生JSON保存至 `data/jilin-samples/traffic/`，只用相对路径，使用已有锁与原件不可覆盖保存函数。配置不得依赖诊断目录或绝对机器路径。
- [x] 临时数据库全量测试→规格复核→质量复核。涉及来源卡展示时验证旧来源输出没有被意外改写。

## 任务3：真实验收、迁移和交付

状态：2026-10-03实际入库和受限交付已完成，独立规格及最终质量复核均通过，无阻断交付问题；保留已有非阻断性能建议。主库48版本/46来源/96审计/48索引/0人工发布；本批6新版本可检索，6候选因格式保真仍阻断，集合complete=false。48版本真实HTTP全文、旧库逐项保留、离线重放、399测试及548载荷本机异路径恢复通过。最终交付为2026-10-03-r2源码包与2026-10-03个人数据包；未第二Mac实测、未完成八表或全国覆盖。证据为同日traffic-live各项记录、traffic-delivery-spec-review和traffic-final-quality-review报告，中文说明见docs/traffic-cell-library-delivery-2026-10-03.md。下列勾选表示相应实施/验收动作已完成，不表示六项格式阻断已解除。此计划不在r2源码包的110项成员中，收尾状态更新不改变已校验的生产代码和交付说明，不为勾选重打包。

文件：新增日期化 `verification/traffic-live-2026-10-03*.json`、中文交付报告；更新相关项目记忆和操作文档。

- [x] 只读重新确认主服务健康、主库逻辑快照及现有42版本、provenance、audit。保存入库前SQLite备份，不能覆盖旧备份。
- [x] 运行有界导入；每份新版本调用真实MCP检索、逐片全文回读并逐字/哈希比较；查不到不能算完成。对不支持的文件展示确切原因。
- [x] 离线重放完全同一原件，确认版本/审计不增加；旧42版本与原来源/审计逐项保持不变。
- [x] 执行 `.venv/bin/python -m unittest discover -s tests`；通过情况、失败项和首次失败证据分开保存，不篡改历史报告。
- [x] 实际export/verify/restore到不同中文/空格路径，检查新原件和表格定位仍可访问。若依赖本机转换，注明迁移安装要求，不称已在第二台Mac实测。
- [x] 更新Obsidian、资料清单和新日期输出包，源码包排除全部案件演练会话与凭据；旧包保留。若存在解析或外部访问阻断，交付明确部分完成及下一步，不夸大为全国完整库。

## 自检

设计中的来源身份、双版本差异、工作表与单元格覆盖、引用展示、旧库保护、幂等和可迁移性分别对应上述任务。未知字段/格式的检查必须产生具体未支持结果，而不是占位“通过”。任务1与任务2为依赖关系，不同时派发修改生产代码的实现者；复核与只读调查可独立进行。
