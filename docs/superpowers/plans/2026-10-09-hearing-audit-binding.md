# 模拟法庭事实关联实施细化（Task 4）

执行：使用 subagent-driven-development、测试先行与独立复核。承接用户已批准的整改计划，不新增审批授权、发布或外部平台。

目标：让单轮发言可以携带可复核的事实、精确文本证据、自认风险和审计关联，而不把机器记录当作律师批准。

架构：在 v2 回合增加可选 audit 字段，既有无 audit 会话保持兼容。audit 与回合、来源回执一起存入原 session.json，沿用同一锁、完整摘要和单次原子替换。不另写权威旁置文件，避免多文件半提交。它是当轮快照，不是覆盖之前快照的“最新真相”。

## 输入契约

audit 恰含 fact_register、admission_queue、attack_links、artifact_ids、corrections 五个列表。

- fact_register 每项恰含 fact_id、speaker、text、time、status、source_refs、contrary_refs、external_use_status。ID 非空且当轮唯一，speaker/text 非空，time 为 null 或非空字符串。状态复用 alleged/supported_by_record/admitted_in_record/judicially_found/hypothetical/disputed/unclear。三个记录型状态必须至少一个 source_ref。external_use_status 只允许 internal_only 或 blocked；不是法律事实认定。
- 每个 source_refs/contrary_refs 定位恰含 material_id、start、end、quote。材料须在 manifest 和当轮 material_ids 中；start/end 为非 bool 整数，0 <= start < end <= 文本字符数；quote 非空且与该 UTF-8 材料的 Python 字符切片严格相同，不是字节位置或 PDF 页码。
- admission_queue 每项恰含 admission_id、text、fact_ids、purpose、risk、reviewer、decision、reviewed_at。ID 当轮唯一，text/purpose/risk 非空，text 必须在当轮发言中逐字出现，fact_ids 非空、唯一、全部对应当轮事实。reviewer/decision/reviewed_at 必须全为 null；真实审批接入不在本步骤内，不允许以记录完整为由对外放行。
- attack_links 是关联索引，不冒充完整 attack-audit-schema 记录。每项恰含 attack_id、fact_ids、admission_review_ids、external_use_status；ID 当轮唯一；事实和风险 ID 必须存在且无重复；external_use_status 为 internal_only 或 blocked，关联风险时只能 blocked。
- artifact_ids 是 manifest 内已准备的 UTF-8 辅助产物 ID，必须唯一且在当轮 material_ids 中。其实际哈希随原 manifest 校验。无自动读取未列明文件，无二进制原件转换或页码真实性证明。
- corrections 每项恰含 turn_index、reason；turn_index 为非 bool 非负整数且指向此前带 audit 的回合，reason 非空，同一目标不重复。该字段只关联更正说明，保留旧回合，禁止指向自己或未来。

## 文件与顺序

- [x] 保存本批前 mock_hearing.py 原件；完整基线重新通过才实施。
- [x] 新建 tests/test_hearing_audit.py：先证明有效 audit 被旧代码拒绝，再测错 ID/错引文/错范围/bool/签名/悬空关联/伪外发/更正越界都不改变原文件。
- [x] 新建 hearing_audit.py 承担结构和引用校验；只在 mock_hearing.py 读取与追加的共同路径接入。保留 create/load/append API，不改旧测试，不自动升级历史会话。
- [x] 测试真实材料读取、load 再校验、原子写失败、旧 v2 无 audit、append-law 兼容、CLI 往返。失败后再最小修复。
- [x] 独立规格复核通过后做质量复核；最终跑完整工程回归，保留真实退出码。
- [x] 更新使用指南与三个 Skill 参考页副本，给出精确契约和“可选不等于全面审查”的边界；实际同步后比对哈希。

本步骤只完成 R2/R3 的结构关联基础。对材料真实性、语义、遗漏风险、真实审批身份、整案二进制原件冻结及律师效果不作机器验收承诺。Task 5 互动复练、Task 6 完整样例与真人评测仍按总计划单独实施。
