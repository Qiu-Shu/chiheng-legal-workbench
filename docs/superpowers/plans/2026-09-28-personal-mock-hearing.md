# 个人本机模拟法庭实施计划

> 按已获用户确认的设计使用subagent-driven-development。只实施民商事一审、个人本机、指定案卷；不中途扩成多用户系统。无Git，保存实际测试和文件哈希。

**Goal:** 交付可以实际走完全部回合并复盘的本机演练流程。

**Architecture:** Skill负责可见发言和法律审查，小型标准库会话模块负责指定材料/哈希/阶段与追加记录；共享MCP只查公开法源，真实私案不入公共库。

**Tech Stack:** Python标准库、既有Skill/MCP、JSON会话、文件锁与原子替换。

## 实际验收记录（2026-10-02）

模块、Skill分支均完成独立规格及质量复核。24专项/337全量工程测试通过；旧Skill真实基线20轮已留证。新上下文使用4份合成材料实际完成17轮，14次MCP、17次追加/18次读取，含暂停恢复；首次整体partial仅来自辅助审计两处P3，保留原件后修正并独立定向复验通过。会话字节未修改，法律人审仍pending。交付及使用详见docs/mock-and-library-delivery-2026-10-02.md与docs/personal-mock-hearing-guide.md；本机/插件同步和打包记录以本轮交付清单为准。

## 1. 会话文件边界与阶段控制

文件：新增`mock_hearing.py`、`scripts/mock_hearing_session.py`、`tests/test_mock_hearing.py`；不修改公开检索服务。

接口约定：

```python
create_session(case_root, packet)  # 返回新session；不覆盖case_root/session.json
load_session(case_root)           # 校验manifest与材料哈希后返回本案记录
append_turn(case_root, turn)      # 锁内校验并原子追加；返回更新会话
```

packet包含case_id、procedure（仅civil_first_instance）、our_role（plaintiff/defendant）、materials（id、relative_path、sha256）。材料UTF-8文本仅由用户显式列入，禁止绝对路径、父目录、符号链接、未知材料ID。只读登记文件，不扫描其他案件、不自动格式转换。材料最多100份、每份最多2MB；限制须明确报错，不截断。

turn包含case_id、stage、role、text、material_ids、source_cards、unresolved。阶段为issues/evidence/questions/debate/review；角色moderator/plaintiff/defendant/reviewer。issues和questions须主持及双方已发言，evidence与debate须双方发言，才能进入下一阶段；review由reviewer发言。只能当前阶段继续或顺序进入下一阶段，不跳跃。准备阶段由create完成，结束后不追加新回合；需续演另建会话而非改旧记录。

只验证可检验结构，不假称文本已经法律正确。source_cards为本轮真实工具返回的待审引用卡；未检索可为空并在unresolved说明，禁止程序生成“已核验”或人工签名。字段为普通可见输出，不存私有思维链。会话记录明确synthetic/真实材料标签和human_review=null，不由模型填已签发。

- [ ] 先失败测试：越界/符号链接/哈希不符/材料未知、跨case_id、阶段跳跃/缺角色、错误程序、重复初始化、并发追加及原子写失败；本案读取成功、旧文件不变。
- [ ] 最小实现上述接口，目录/文件权限限制仅用于本机存储，不宣称同账号或多用户身份授权。CLI提供init/read/append，帮助输出解释状态与限制，错误非零退出。
- [ ] 规格及质量独立复核，相关与全量测试通过。不向公共DB或Obsidian写案卷。

## 2. Skill分支与实测

文件：修改核心`SKILL.md`的明确模拟法庭入口，新增`references/mock-hearing.md`及必要合成案件模板；本机/插件同步留至前向验收后。

- [ ] 用当前未新增分支的Skill完成一次合成模拟法庭任务，保存完整基线输出与实际缺口。
- [ ] 仅针对基线缺口加入已批准阶段、每轮角色、来源与案卷边界、会话模块用法和复盘交付；不改变原A/B审查标准。
- [ ] 新上下文用一份指定合成案件走完整阶段，真实调用共享MCP并保存全部回合。查不到或未核的新鲜度保持未知，模拟法官意见不作裁判预测。
- [ ] 独立审阅会话输出与来源回读记录，验证无新增事实、自认/签发、遗漏反方意见或伪造检索；B44多用户权限仍不宣称通过。
- [ ] 同步经验证的本机和插件Skill，校验哈希，更新中文使用指南与交付包。

## 完成口径

本模块的首版完成只表示合成民商事一审演练及对应工程/行为验收完成。刑事行政执行、真实律师试用、真正多用户权限、全国库穷尽及ChatGPT账号联通仍有独立完成条件。
