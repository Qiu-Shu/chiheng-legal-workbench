# 个人本机模拟法庭

仅在用户明确要求模拟法庭时进入；首版只支持 `civil_first_instance`（民商事一审），`our_role` 必须明确为 `plaintiff`（原告）或 `defendant`（被告）。缺这两项或指定材料范围时，只补问必要信息。刑事、行政、执行不套用本分支。

## 准备与边界

沿用主技能每次必读参考页；涉及法律依据时还须读取来源规则、工具契约和[运行与版本提示](runtime-and-release.md)。双方立场仍应用 A/B 三遍审查及原事实状态、自认和律师审批规则。模拟主持仅整理争点和发问，不作事实认定；无法回答不自动视为自认。缺证据不等于事实不存在，模拟回答不成为新增证据。

说明同一模型可扮演多个角色，并非独立律师团队；本次为内部演练，不预测胜率，不提交法院，不签发。真实材料进入模型对话仍涉及传输，“本机存储”不等于本地推理；按已有案件授权与保密要求使用。

只使用用户本次明确列入的材料，不扫描其他案卷或把旧案当作补充材料。准备一个新建的专用 `0700` 目录；不得修改已有用户目录的权限以绕过检查。若已有目录不合格，使用新的专用目录。将指定材料整理为该目录内的 UTF-8 文本，最多 100 份，每份最多 2MB。其他格式用适用工具明确转换并保留原件和转换说明，不能声称会话模块验证了原格式。

登记每份材料的唯一 ID、目录内相对路径与实际字节 SHA256（64 位小写十六进制），禁止绝对路径、父目录跳转、符号链接、硬链接与会话文件名。只复制或转换本次指定文件；哈希缺失或不符时停止相关读取和追加，不自行换材料。会话、回合与真实私案不写入公共法律库、公共索引、Obsidian 或分发包。

## 使用已有会话程序

复用已安装共享源码目录中的 `mock_hearing.py` 和 `scripts/mock_hearing_session.py`；先从宿主配置或本项目路径确认真实目录并检查脚本可用。可分发 Skill 不自带该模块或依赖，不能硬编码某台电脑的路径、假称程序已安装，或另写一套保存逻辑。缺程序时说明持久会话未完成，保留准备工作。

| 程序接口 | CLI | 使用时机 |
| --- | --- | --- |
| `create_session(case_root, packet)` | `init --case-root … --input …` | 新演练先创建，成功后才开始回合，禁止覆盖 |
| `load_session(case_root)` | `read --case-root …` | 续演先验证材料/清单哈希、全部回合及当前状态 |
| `append_turn(case_root, turn)` | `append --case-root … --input …` | 每条单角色发言写入后再继续；失败则停止该次追加 |
| `hearing_sources.append_law_turn(case_root, turn, sources)` | `append-law --case-root … --input …` | 由程序读取本地法库片段、关联命题并保存完整返回；不接收手填引用卡 |
| `hearing_progress(case_root)` | `progress --case-root …` | 只读列出已登记争点的问题、任务和法律待核事项 |
| `create_rehearsal(case_root, packet, previous_case_root, focus)` | `rehearse --case-root … --previous-case-root … --input …` | 从明确指定的已完成v2演练建立关联的新演练；不复制旧回答 |

在已确认的共享源码根目录执行；下列变量分别是明确选定的专用目录、案件包 JSON、单回合 JSON 的路径，先赋实际值。`read` 不接收 `--input`。JSON 输入也是 UTF-8 文本。

```sh
python3 scripts/mock_hearing_session.py init --case-root "$rehearsal_root" --input "$packet_file"
python3 scripts/mock_hearing_session.py read --case-root "$rehearsal_root"
python3 scripts/mock_hearing_session.py append --case-root "$rehearsal_root" --input "$turn_file"
```

`packet` 恰含以下字段，不添加模型自拟字段：

- `case_id`：非空案件标识；不同案件不得混用，同一案件的关联复练沿用该标识，以不同专用目录区分各次演练。
- `procedure`：`civil_first_instance`。
- `our_role`：`plaintiff` 或 `defendant`。
- `materials`：列表，每项恰含 `id`、`relative_path`、`sha256`；文件须已准备好。无材料时如实为空，并说明事实基础缺失。
- `synthetic`：布尔值；只有全部是明确合成材料才为 `true`，真实或混合材料为 `false`。
- `human_review`：始终为 JSON `null`，不生成律师签名或审批。

程序生成 `manifest_sha256`、`turns`、`stage`、`completed`，保存至目录内 `session.json`（`0600`）。新会话还生成 `schema_version=2` 和覆盖完整会话内容的 `content_sha256`；不要手改会话文件。每次追加在锁内重新校验并原子写入；材料、发言或卡片改变而未同步重算摘要时会被发现，跨案标识、非法阶段或角色也会拒绝。摘要不是签名，不能防止同账号人员重写内容、重算摘要或删去版本字段。校验失败时报告实际错误，不能绕过校验续写。

同时缺失 `schema_version` 和 `content_sha256` 的历史格式仍可原样读回，但只能只读，不能续写或补写“当时已核验”的回执。只缺其中一项属于不完整格式，须停止，不得删去剩余字段将它降级成旧格式。需要继续训练时另建专用目录，明确它是新演练；不得覆盖旧会话或自动复制旧发言当作新发生的回答。

## 阶段与逐轮记录

准备由创建会话完成，随后只按下表顺序前进，可在当前阶段继续发言，不跳跃或回退。完成必要角色只是结构下限，仍须实际回应对方主张和证据。

| stage | 内容 | 进入下一阶段前的必要角色 |
| --- | --- | --- |
| `issues` | 争点整理 | `moderator`、`plaintiff`、`defendant` 各至少一回 |
| `evidence` | 举证质证 | 原告、被告各至少一回 |
| `questions` | 主持及双方发问、回应 | 主持、原告、被告各至少一回 |
| `debate` | 双方辩论与反方回应 | 原告、被告各至少一回 |
| `review` | 完整复盘 | 仅 `reviewer` 一回，保存即完成 |

每轮 `turn` 必填 `case_id`、`stage`、`role`、`text`、`material_ids`、`source_cards`、`unresolved`。`text` 保存一个角色的完整可见发言，不能把双方合并一条；只保存可审核分析摘要，不保存模型私有思维链。`material_ids` 只能用清单内的 ID，正文就近注明相应材料及定位；未知页码不得编造。程序为每轮补入与会话一致的 `synthetic` 和 `human_review: null`。

`source_cards` 保留本轮实际检索返回。普通 `append` 只检查每项为非空 JSON 对象，不认证来源；不能把对象存在写成检索或法律核验通过。不得把模型记忆、链接标题、镜像标签写成实际工具返回，不能伪造“最新有效”或已核验。未检索或无法核验时用空列表，并在 `unresolved`（非空说明字符串的列表）写明原因；有来源但仍不确定也继续记录。遵守访问限制，不向法律检索工具传入私案全文。

本轮使用共享本地法库片段时，先检索定位版本和片段，再使用 `append-law`。输入 JSON 恰含 `turn` 与 `sources`；`turn` 沿用上述回合字段，但 `source_cards=[]`，由程序生成。每个 `sources` 对象恰含 `claim`、`version_id`、`offset`、`length`，最多10项；`claim` 是发言 `turn.text` 中实际出现的法律命题，位置从0计、长度1至10000字符。

入口直接调用现有本地 `get_law_fragment` 实现，只有版本号和片段位置进入查询。保存卡包含 `tool`、`arguments`、完整 `result`、`claim` 和 `receipt_id`；引用时展示 `result.citation` 及 `result.text`，不得把外层回执编号当作官方链接。待核日期、quarantine及适用性状态原样保留。命题出现在发言中，只是关联检查，不能证明原文支持该命题；仍须核对上下文、时点及适用条件。

该入口不是本轮联网核验或外部MCP传输验收。来源不存在、正文为空、撤回或返回定位不一致时，不追加回合；不得改用普通 `append` 冒充回执成功。如需继续条件式讨论，使用空引用并写清失败原因。其他检索工具目前没有这一适配，不得伪造其回执。无新入口时如实报告组件缺失，不另造已核记录。

默认逐轮互动：保存主持提问后等待用户回应；按实际内容保存对应原告或被告回合。用户明确要求一次完整合成演练时，可由同一模型依次生成所有角色并逐条追加；不冒充真实当事人陈述、独立律师意见或人工审批。无论哪种方式，都须有质证、反方回应和复盘。

暂停时说明本次保存位置和当前阶段；恢复时先 `load_session` / `read`，只从已验证状态继续，不能凭聊天记忆新建一份替代旧记录。`review` 一次保存完整复盘后即结束，不能再追加；新演练另建专用目录，不覆盖旧会话。

## 事实、证据与风险关联快照

需要保存结构化审查关系时，在本轮 `turn` 中增加可选 `audit`，仍使用 `append`，或将它放入 `append-law` 的 `turn`。先确认当前共享源码支持此字段；旧程序不支持时明确报告，不改写会话文件绕过。已有无 `audit` 的 v2 回合仍可读取，但不能称其已完成结构化审查。材料未提供或尚未整理时，保留缺口说明，不编造登记项。

`audit` 恰含五个列表：`fact_register`、`admission_queue`、`attack_links`、`artifact_ids`、`corrections`。均保存在本轮会话内，与来源回执一起受完整摘要覆盖；没有第二份需要同时提交的权威文件。每次是当轮快照，不能用后来的空列表声称旧风险已消除。

- `fact_register` 每项恰含 `fact_id`、`speaker`、`text`、`time`、`status`、`source_refs`、`contrary_refs`、`external_use_status`。ID 当轮唯一；speaker/text 非空；time 未知为 `null`，已知为非空文字。status 复用 `alleged / supported_by_record / admitted_in_record / judicially_found / hypothetical / disputed / unclear`；三个记录型状态必须提供支持定位。external_use_status 仅为 `internal_only` 或 `blocked`。选择状态是待审分类，不是程序认定事实。
- `source_refs` 和 `contrary_refs` 为定位对象列表，每项恰含 `material_id`、`start`、`end`、`quote`。材料必须同时列入本会话清单和本轮 material_ids；位置按解码后 Python 字符计数，从0开始、末端不含，要求 `0 <= start < end <= len(text)`，不得使用 bool。quote 必须与切片逐字一致，不能改写引文、使用 UTF-8 字节数或冒称 PDF 页码。原页及转换关系仍须另核。
- `admission_queue` 每项恰含 `admission_id`、`text`、`fact_ids`、`purpose`、`risk`、`reviewer`、`decision`、`reviewed_at`。ID 当轮唯一；text/purpose/risk 非空；text 必须逐字出现在本轮发言，fact_ids 非空、无重复并指向当轮事实。三个审批字段必须为 `null`，该入口不接收真实审批，也不得代填。引用风险句用于内部检查，不代表允许对外使用。
- `attack_links` 是关联索引，不代替完整攻击审计表。每项恰含 `attack_id`、`fact_ids`、`admission_review_ids`、`external_use_status`；ID 当轮唯一，引用列表不重复且全部存在于当轮相应登记。状态只允许 `internal_only` 或 `blocked`；关联任何自认审批项时只能为 `blocked`。
- `artifact_ids` 是辅助产物材料 ID 列表，无重复，须同时位于清单及本轮 material_ids。产物必须在创建会话前准备好并登记实际哈希；仅覆盖这些 UTF-8 文件，不自动冻结目录中其他产物或二进制原件。
- `corrections` 每项恰含 `turn_index`、`reason`。turn_index 是已有 turns 列表中从0计数的位置，只能指向此前带 audit 的回合，不接受 bool、自己、未来或重复目标；reason 非空。更正另写在当前发言和快照里，不覆盖旧回合，也不自动撤销原风险。仍须遵守阶段规则，完成后的会话不能续写。

例如材料 `M1` 的完整文本是 `甲称已付款。乙否认。`，则 `{"material_id":"M1","start":0,"end":5,"quote":"甲称已付款"}` 是可验证定位；它只证明文字位于该处，不能证明付款已发生。

校验失败时该轮不保存，不通过删掉 audit 将失败的关联冒称为成功。无字段或空列表不表示没有风险；程序不识别遗漏的自认句、不认证材料真实性或审批身份，也不决定引文与主张的语义关系。真实审批接入及对外放行仍待另行验收。

## 逐争点追问、任务与法律待核

需结构化追踪时，在v2回合增加可选 `tracking`，与 `audit` 并列，仍由 `append` 或 `append-law` 保存。tracking恰含 `issue_id`、`questions`、`responses`、`tasks`、`law_checks`；issue_id是非空字符串，其余为列表。每轮只关联一个争点；无此字段的历史回合保持原样，不补称已追踪。

- questions每项恰含 `question_id`、`text`、`addressed_to`。ID在整个会话唯一；text非空并逐字出现在本轮发言；addressed_to为plaintiff或defendant。主持提问后等待用户回应，未收到答复不得自行填写真实当事人的回答。
- responses每项恰含 `question_id`、`kind`、`text`。只能指向此前回合、同一争点、提问对象与当前role相同的问题，同轮ID不重复；kind为 `answer` 或 `unable_to_answer`，text非空并逐字出现在发言。后续可以补答同一问题；进度保留全部回应回合，按最后一种回应展示。有回答不代表争点解决，暂不能回答仍列未答/待补，不算自认。
- tasks每项恰含 `task_id`、`text`、`kind`、`status`、`material_ids`、`review_note`。ID非空且当轮唯一；text非空；kind为 `evidence/law/wording`；status只允许 `open/addressed_pending_review`。材料ID不重复且须属于本轮material_ids；review_note为null或非空文字。同一任务的后续事件不得改issue_id、kind和text；需要不同任务就用新ID。
- 标为 `addressed_pending_review` 必须填写review_note；evidence任务还要关联至少一份材料，law任务还要有本轮law_checks。任务可以重新open；省略或空列表不删除历史任务。已处理仍待律师复查，没有approved或resolved状态。清单外的新材料须另建演练显式登记，不能改旧manifest；本轮只能关联原清单已有材料。
- law_checks每项恰含 `claim`、`source_card_index`、`fact_date`、`research_as_of`、`temporal_note`、`transition_note`、`applicability_note`、`status`。claim非空并在本轮发言中逐字出现；source_card_index为null或本轮source_cards从0计的下标，不接受bool。两个日期为null或真实 `YYYY-MM-DD` 日期；三个note为null或非空文字；status只为 `needs_review/blocked`。字段缺失信息用null，不能补造日期或“已核”。卡片下标存在不认证其来源，也不证明时效、过渡条款或案件适用；法律引用仍须展示原来源卡及原文。

调用 `progress --case-root …` 不接收input、不写新文件。它从已验证历史派生 `case_id`、`structural_completed`、`tracking_recorded`、`issues` 和 `notice`。issues按首次出现顺序列出问题、`unanswered_question_ids`、任务最后事件、`pending_review_task_ids` 和法律待核记录。pending_review_task_ids仅含addressed_pending_review任务；open任务仍列在tasks中，不据前者为空推断没有待办。问题保留 `question_turn_index`、`latest_response_kind`、`response_turn_indices`；任务和法核记录保留 `turn_index`，这些回合位置均从0开始。无tracking时标记false和空issues，不能解释成“无争点或无缺口”。任务和法律待核项即使流程完成也保留。

角色沿用现有约定：反方围绕我方具体论点作回应；主持整理问题及指向，不认定事实；reviewer在review阶段给出训练复盘，不签发裁判。不要把同一模型的多角色发言说成独立律师评审。

## 关联下一次复练

用户明确指定已完成旧演练、新专用目录、新材料包和本次目标后，使用 `rehearse`。input恰含 `packet` 和 `focus`；packet沿用原创建字段，focus为非空、无重复的目标文字列表，不是审批或自动认定的问题ID。先确认当前安装版本提供该入口；缺失时不能手写关联字段。

程序实际读取并校验指定旧目录，只接受已完成v2，新旧case_id、procedure、our_role、synthetic须一致，目录必须不同。新材料全部由packet明确列出，不扫描旧案卷；创建时一次保存 `rehearsal_of`，其中 `case_id/content_sha256/turn_count` 由程序从旧会话取得，focus为指定目标。关联不包含绝对路径，旧会话字节不变；新turns为空，不复制旧回答、审批或已处理状态。要复练的问题和任务在新会话重新登记。

关联只是创建时旧记录的定位，不是数字签名；读取新记录时不自动重访旧目录，也不证明旧文件现在仍未变化。旧格式不支持该关联入口；普通新演练可以另建，但不得称其已通过复练关联核验。禁止覆盖旧会话，禁止先创建普通会话再手改补入关联。

## 复盘与完成口径

复盘至少给出争点清单、双方强弱意见、证据缺口、主持可能追问、需修正文句、待核法律及下一步。区分当事人主张、材料显示、争议与假设；不能把模拟主持的疑问写成法院已认定事实。完成后再次读取会话，确认全部阶段、双方发言及复盘均已保存，再告知演练完成。

文件检查和锁仅约束本模块，不能隔离同一操作系统账号下的其他工具，也不是宿主全局或多用户案件权限保证。B44 真实跨案身份权限仍未验；本次合成演练、结构校验或来源回读均不代替律师法律审核。不要为本分支新增认证平台、服务 API、模型账户或收费方案。
