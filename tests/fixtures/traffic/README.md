# 交通裁量表测试原件

这四个文件是公开附件的逐字节副本。测试直接使用本目录，不依赖本机 `verification` 目录，也不在测试期间下载原件。哈希为 SHA-256；文件名仅为测试便于识别，原文未更改。

## construction.xlsx

- 附件2-7：交通建设监督管理及其他。
- 来源：https://www.jlrd.gov.cn/jlsjk/202608/P020260806339634139468.xlsx
- SHA-256：`8c1b11d3e3d14568ec5911a6ed29fad376c42dc3b4dccbbe7308e0eb57bf54c4`
- 2026-09-28保存；C55保留原件“不与退还”，不得替换为另一个来源版本。

## construction-government.xlsx

- 附件2-7：交通建设监督管理及其他，政府来源差异版本。
- 来源：https://xxgk.jl.gov.cn/zcbm/fgw_98037/xxgkmlqy/202607/P020260817491867840900.xlsx
- SHA-256：`fcb84ac555e70bdecde03f886e1f713778b90a7af1459c8c58007c3213edf75a`
- 2026-10-03保存，C55为“不予退还”；兼容性元数据支持只认证此固定原件的静态全格读取，任何字节变化须重新核验，未验收私有筛选UI行为。

## transport.xlsx

- 附件2-1：道路运输和城市客运管理。
- 来源：https://www.jlrd.gov.cn/jlsjk/202608/P020260806339633416643.xlsx
- 同字节来源（2026-10-03核验）：https://xxgk.jl.gov.cn/zcbm/fgw_98037/xxgkmlqy/202607/P020260727327347415415.xlsx
- SHA-256：`fb57f44caeb05e11c44fdd151cd3ee965dd0e428af3297760d3121efae30a6df`
- 包含空Sheet2和两处合并范围，不能仅保留首表。

## highway.xls

- 附件2-2：公路路政管理。
- 来源：https://www.jlrd.gov.cn/jlsjk/202608/P020260806339633523848.xls
- 同字节来源（2026-10-03核验）：https://xxgk.jl.gov.cn/zcbm/fgw_98037/xxgkmlqy/202607/P020260727327347576297.xls
- SHA-256：`fb163cf8da6166ebfd841c56f1c62361fd64c0c5bc26f8d54813cb5d6a07eef1`
- 仅验证逐格和富文本run保存；BIFF/OLE完整显示语义未核验，必须保持投影门禁。

来源记录据原采集审计 `verification/remaining-jilin-probe-20260928` 及 `verification/traffic-cross-source-2026-10-03/network.json` 摘录。测试通过不代表法律效力或律师审核结论。
