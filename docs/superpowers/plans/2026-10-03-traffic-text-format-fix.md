# 交通文字格数字格式误报修复计划

> 执行方式：本轮沿用已批准的交通逐格定位设计，按executing-plans在当前会话实施。独立代理账户额度中断仍未恢复，不把自检作为独立审查。

**目标：** 消除公路表168个文字格的已证实数字格式误报，不解除五XLS的BIFF/私有扩展门禁，不改变主库或历史诊断。

**架构：** 复用现有单元格读取和门禁，仅在_check_cell中对已核验的单节数字格式`0\.0,"万"`且值类型为s/inlineStr认可文字原样展示。数字值仍拒绝该格式，其他格式/四节文字隐藏/颜色/富文本门禁不变。不新增通用格式解释器。

**依据：** Microsoft官方自定义格式说明：未含文字节的数字格式不影响非数字文字。原件SHA fb163cf8da6166ebfd841c56f1c62361fd64c0c5bc26f8d54813cb5d6a07eef1，168格均为s；使用已有LibreOffice派生物再次全格比较，不重新转换或修改原件。

## 1. 基线和先失败测试

文件：tests/test_traffic_workbooks.py；verification/traffic-text-format-*-2026-10-03.json与日志。

- [x] 保存主库逻辑摘要、544个data文件（SQLite运行时SHM/WAL除外）/20旧ZIP摘要和五XLS、五成功XLSX当前结构摘要，证据新建不覆盖。
- [x] 新增真实公路168文字格无number_format误报且BIFF仍阻断测试；新增纯文本（含数字外观字符串）原样保留而数字值仍阻断测试；新增该格式的四节/颜色/后缀变体仍阻断测试。
- [x] `.venv/bin/python -m unittest discover -s tests -p test_traffic_workbooks.py`。实际40测试含4子测试失败，原因正是预期误报，不是脚本错误。

## 2. 最小修改及回归

文件：traffic_workbooks.py的_check_cell。

- [x] 只新增以下例外，不动cell_snapshot/display_number或XLS审计：

```python
text_with_numeric_format = (cell["value_type"] in ("s", "inlineStr")
                            and cell["number_format"] == r'0\.0,"万"')
```

- [x] 原number_format拒绝条件附加`and not text_with_numeric_format`；display_text为None仍拒绝，字体/隐藏/未知扩展门禁独立执行。
- [x] 69项工作簿/集合专项、407项全量通过；已为本机回环端口验证取得执行许可。依赖的既有弃用警告保留，不修改无关依赖。

## 3. 实物核对与交付

- [x] 五XLS前后只有公路168项number_format诊断移除，全部格/合并/观察信息不变，五份仍阻断。168文本值/类型与既有转换件一致，转换格式字面规范化差异单列；不称完整视觉或ETExtData验收。
- [x] 成功五XLSX完整快照与修复前及现有data归档不变；544个data文件、主库逻辑摘要、20旧ZIP不变，实际共享服务仍49版本。
- [x] 中文修复报告和113成员源码r4实际生成及逐字验证；沿用数据r2，不重新导出/入库。r3和全部旧诊断保留。
- [x] 指定三个Obsidian项目文件取得写权限并同步本轮事实，保留五XLS/WPS/独立复核缺口；未扩大到整个vault。

额外只读调查：尝试本机WPS公开原件工作副本；文件选择路径输入未成功，已取消，未取得原生核验证据。详情见本轮报告，不改变既有门禁或上述完成口径。独立复核、五XLS保真验收仍未完成。

自检：这是原方案读取规则的窄修复；不新增法律资料、效力结论、罚款计算、私有格式逆向或公开发布。本项目非Git仓库，不伪造提交。五XLS以及独立复核仍待完成。
