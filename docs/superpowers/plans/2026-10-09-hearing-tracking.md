# 争点追问与复练实施细化（Task 5）

按用户已批准的整改计划执行，使用 subagent-driven-development、测试先行和独立规格/质量复核。沿用标准库和单会话原子保存，不新增代理框架、模型账户或审批平台。

## A. 单轮跟踪与只读进度

在 v2 turn 增加可选 tracking 对象，恰含 issue_id、questions、responses、tasks、law_checks。issue_id 为非空字符串；其余为列表。JSON转换不得隐式将元组变列表。既有无tracking回合不变，不称其已完成争点跟踪。

- questions 每项恰含 question_id、text、addressed_to。ID 全会话唯一，text 非空且逐字出现在本轮发言中；addressed_to 为 plaintiff 或 defendant。问题属于本轮issue_id。
- responses 每项恰含 question_id、kind、text。目标须为此前回合的问题，属于同一issue_id，且其addressed_to与当前role一致；本轮不可重复回答同一ID。kind 为 answer 或 unable_to_answer；text非空且逐字出现在本轮发言中。可以在后续回合再次回应同一问题，保留全部记录，进度展示最后一种回应及所有回应回合。unable_to_answer仍列未回答/待补，不算自认；answer只表示有回答，不代表争点解决。
- tasks 每项恰含 task_id、text、kind、status、material_ids、review_note。ID非空、当轮唯一，text非空，kind 为 evidence/law/wording，status为open/addressed_pending_review。material_ids为无重复字符串列表，必须属于本轮material_ids；review_note为null或非空文字。后续可更新同一task_id，但issue_id、kind和text不得改变。addressed_pending_review必须有review_note；evidence类型还需至少一个材料，law类型还需本轮至少一条law_check。任务可重新open，不能自动删除或写成已律师批准。更新是新事件，原事件保留。
- law_checks 每项恰含 claim、source_card_index、fact_date、research_as_of、temporal_note、transition_note、applicability_note、status。claim非空且出现在本轮text中，source_card_index为null或非bool非负整数且对应本轮source_cards；日期为null或严格YYYY-MM-DD实际日期。三个note是null或非空字符串，status仅needs_review/blocked，不能填写verified。缺少来源或日期允许记录待核；下标存在只说明卡片位置，不认证普通append来源、不证明语义适用或现行性。

新增 hearing_tracking.py：单遍重放已验证回合、校验跨回合关联、派生只读进度。既有load和append共同接入，继续由session摘要覆盖tracking；更改后重算摘要也不能绕过结构/关联检查。不要在磁盘另存一份权威进度。

新增 mock_hearing.hearing_progress(case_root)，CLI progress --case-root（无input）。返回case_id、structural_completed、tracking_recorded、issues及明确notice。issues按首次出现顺序，包含issue_id、questions（保留题目和提问回合、最后回应类型及所有回应回合）、unanswered_question_ids、tasks（最后事件的内容及回合）、pending_review_task_ids、law_checks（附回合位置）；所有任务只属open或待审，不推出争点胜负。没有tracking时issues为空且tracking_recorded=false，不解释为无问题。主持/反方/教练的区别由既有role和Skill应用，不新增角色或权限。

## B. 复练关联

新增 create_rehearsal(case_root, packet, previous_case_root, focus) 与CLI rehearse --case-root … --previous-case-root … --input …。input恰含packet、focus；focus为非空无重复字符串列表，表示用户指定目标，不是自动判断。

必须实际load_session指定旧目录；仅允许已完成v2，且新旧case_id/procedure/our_role/synthetic一致，新旧目录不同。新材料仍由packet显式列明，不扫描或复制旧案卷。新会话turns为空，在同一次创建保存中加入rehearsal_of，恰含case_id、content_sha256、turn_count、focus。前三项由程序取旧会话，不接受调用者提供。读取新会话时严格检查这些字段（case_id一致，64位小写摘要，非bool正整数回合数，focus如上），只核验本地结构，不假称每次重新访问旧文件或认证其当前状态。

关联不存绝对路径，迁移后可读；它是创建时实际读到的旧会话定位，不是签名。旧会话字节不变，不把旧回答/审批/任务完成状态复制为新事实，需复练的问题和任务在新会话重新登记。普通create_session API及输入保持原样，可提取共同私有创建函数复用；不先建会话再第二次补写关联。新会话创建失败不遗留无关联session。legacy父会话不在首版复练接口范围内，可人工另建普通演练但不得追认旧记录。

## 文件和验收

- [x] 原490项基线通过，保留mock_hearing.py与CLI原件。
- [x] A测试先失败：有效tracking、问答目标/角色/时序、唯一ID、跨争点拒绝、未回答不等于自认、任务重开/待审、日期/来源范围、伪核验拒绝、tuple、无tracking兼容、摘要重算后的load验证、CLI进度及失败字节不变。实现后独立规格再质量审查。14项新增，均通过。
- [x] B测试先失败：实际已完成父会话、关联由程序生成、目标字段拒绝、跨案/角色/真假/未完成/legacy父会话拒绝、新旧同路径/覆盖拒绝、原子失败、旧文件字节不变、CLI往返、改关联后重算摘要仍严验。独立规格再质量审查。17项新增，均通过。
- [x] 参考页前测和后测，实际按生成输入运行保存/进度/复练；同步三处Skill并比对。
- [x] 完整回归及运行清单，报告工程范围和真实律师评测、原始文件冻结、全国法库、迁移包/第二Mac/云端等未完成项。主代理521项通过；详../../hearing-tracking-rehearsal-status-2026-10-09.md。

源文件限mock_hearing.py、scripts/mock_hearing_session.py、新hearing_tracking.py；测试test_hearing_tracking.py、test_hearing_rehearsal.py。不改既有测试以抹平失败。细化为两个顺序任务，不能同时修改同一模块。
