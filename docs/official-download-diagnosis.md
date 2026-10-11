# 官方下载接口诊断与单份原件验收

日期：2026-09-27。用途：个人非商业学习。本轮从只读诊断扩展为用户授权的 4 处最小源码修复；未升级整个上游项目、未重启 MCP、未读取 `.env`/Cookie/Token。仅下载《中华人民共和国民法典》一份官方原件；未重建或替换旧法律库。

## 1. 下载报错的确定原因

本机 `国家法律法规数据库MCP/scripts/server.py:245` 原来发送 `fileType=docx`。它与该项目已有 API 说明不一致：

`/Users/songmenglvshi/Documents/Codex/2026-06-25/wo-s/work/menglu-legal-treasury/sources/legal-tools/国家法律法规数据库MCP/references/05-flk-api-reference.md:174`

该文档规定单文件接口参数为 `format`、`bbbs`、可空 `fileId`。本轮以同一《民法典》ID做单变量验证：

| 请求 | 实际业务响应 |
| --- | --- |
| `GET /law-search/download/pc?bbbs=ff808081729d1efe01729d50b5c500bf&fileType=docx` | `{"msg":"系统异常","code":500}` |
| `GET /law-search/download/pc?bbbs=ff808081729d1efe01729d50b5c500bf&format=docx` | `code=200`、操作成功、包含官方对象存储下载 URL |

第二次只改参数名，没有登录、绕过访问限制、关闭证书校验或改变法律 ID；可空的 `fileId` 未传也成功。这直接支持“错误下载参数”是本次失败原因。官方可重复请求入口为[下载 API](https://flk.npc.gov.cn/law-search/download/pc?bbbs=ff808081729d1efe01729d50b5c500bf&format=docx)。临时签名只在进程内用于下载，没有写入报告或文件元数据。

## 2. 与指定上游版本的比较

对照提交：`15d7f7646cdb6fbcaeaf9a145c9e22b0cb3ef93e`，仓库 `moyupeng0422/legal-tools`。

| 部分 | 本机修复前 | 指定上游 | 判断 |
| --- | --- | --- | --- |
| 下载参数 | `fileType` | 下载工具与 `_download_and_convert` 仍用 `fileType` | 直接升级不能修复本次错误 |
| 全文导出 | 从详情树的标题生成 Markdown | 加入 DOCX 下载、pandoc 转换与正文清洗，失败时明确标注目录骨架 | 可参考复用流程，但须先修正下载参数并验收清洗结果 |
| 二进制下载 | 客户端无此方法 | 新增独立 HTTPX 客户端下载二进制 | 能作为实现参考；没有解决错误查询参数 |
| 案例 TLS | `httpx.AsyncClient(verify=False)` | 改用 aiohttp，但仍 `TCPConnector(ssl=False)` | 上游仍关闭证书校验，不是此风险的修复 |

证据：[上游国家库 server.py](https://github.com/moyupeng0422/legal-tools/blob/15d7f7646cdb6fbcaeaf9a145c9e22b0cb3ef93e/%E5%9B%BD%E5%AE%B6%E6%B3%95%E5%BE%8B%E6%B3%95%E8%A7%84%E6%95%B0%E6%8D%AE%E5%BA%93MCP/scripts/server.py#L221)、[client.py](https://github.com/moyupeng0422/legal-tools/blob/15d7f7646cdb6fbcaeaf9a145c9e22b0cb3ef93e/%E5%9B%BD%E5%AE%B6%E6%B3%95%E5%BE%8B%E6%B3%95%E8%A7%84%E6%95%B0%E6%8D%AE%E5%BA%93MCP/scripts/client.py#L63)、[export_formatter.py](https://github.com/moyupeng0422/legal-tools/blob/15d7f7646cdb6fbcaeaf9a145c9e22b0cb3ef93e/%E5%9B%BD%E5%AE%B6%E6%B3%95%E5%BE%8B%E6%B3%95%E8%A7%84%E6%95%B0%E6%8D%AE%E5%BA%93MCP/scripts/export_formatter.py#L136)、[案例库 client.py](https://github.com/moyupeng0422/legal-tools/blob/15d7f7646cdb6fbcaeaf9a145c9e22b0cb3ef93e/%E4%BA%BA%E6%B0%91%E6%B3%95%E9%99%A2%E6%A1%88%E4%BE%8B%E5%BA%93MCP/scripts/client.py#L128)。

本轮未复制整套上游导出器。`pandoc` 当前不在本次 shell 的 PATH 中，全文提取改用 DOCX 内部 XML，未安装新依赖。原许可证保留；所有源码变化均有原始备份。

## 3. 官方原件与可搜索文本

保存目录：

`/Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review/data/official-samples`

| 文件 | 内容与校验 |
| --- | --- |
| `civil-code-ff808081729d1efe01729d50b5c500bf.docx` | 官方提供的原件，197,879 字节；下载 HTTP 200，TLS verify result=0 |
| `civil-code-ff808081729d1efe01729d50b5c500bf.txt` | 按正文 XML 段落顺序抽取的 UTF-8 文本，331,282 字节；不是重新分条索引 |
| `civil-code-ff808081729d1efe01729d50b5c500bf.metadata.json` | 来源、时间、两份哈希、抽取方法、结构计数及未审核状态 |

- 官方条目：[中华人民共和国民法典](https://flk.npc.gov.cn/detail?id=ff808081729d1efe01729d50b5c500bf)。
- 对象地址（去除签名查询）：`https://flkoss.obs-bj2.cucloud.cn/prod/20200528/827f65fcb68f40cb941eed996c5212b0.docx`。它用于追溯对象，不保证去掉签名后可直接下载。
- 下载时间：`2026-09-27T16:00:55+08:00`。
- DOCX SHA-256：`6926a597a66c5aad4803591ce9a51a8eebe847260f5ba2805210b608ded78353`。
- TXT SHA-256：`9af653098ceb7ab93086715ae236eca798bd9dc68d432e669240f7e0d052ee36`。

自动化检查：文件识别为 Word 2007+；`unzip -t` 与 `ZipFile.testzip()` 均通过 CRC。`word/document.xml` 可解析，2,654 个段落，2,403 个非空段落；正文中 0 个表格元素、0 个绘图元素。首个非空段落是法律标题，第三条和第一千二百六十条均有正文。

抽取保留 `w:t`、制表符和换行，按正文段落文档序写出；未渲染页面、未做 OCR，也未把页眉页脚、脚注等独立部件并入正文。虽然此样本未见正文表格/绘图，仍不能将本方法推广为所有法律附表、图示与版式的完整保真方案。目录与正文可能重复出现条号，因此条号计数只是机械观察，不等于法律全文已人工审核完整。所有样本元数据保持 `quarantine`，没有生成“人工已核验”记录或执行发布。

主任务随后复核 DOCX/TXT 哈希，并将这一份 TXT 添加到现有 SQLite 隔离区，版本 ID 为 `e1bf7c35af05669481d2a8120044d7f69b724cac1ad44f6f20aeead4dfe54caa`。主任务实测“第一百零一条”可检索；库状态为 **3 个版本、0 个已发布版本**。此操作没有替换旧 JSON 的 2,190 个版本，没有审批发布，也没有把单份官方样本扩展为全库完整性结论。

## 4. 旧《民法典》索引的 198 个漏拆条号

进一步检查查明：旧 `china-law/scripts/build_index.py` 的条号正则没有包含“零”。

| 观察 | 数量 |
| --- | ---: |
| 官方 DOCX 正文段落起始条号（字符类包含零/〇） | 1,260 个，唯一标签 1,260 个 |
| 其中含“零”的条号 | 198 |
| 旧 JSON 的《民法典》条文单元 | 1,062 |
| 旧 JSON 顶层 article 字段含零/〇 | 0 |
| 在旧 JSON 单元正文内找到的含零条号 | 198 次，198 个唯一标签 |
| 容纳上述合并正文的旧单元 | 12 个 |

明确样例：第一百条的 `text` 内含第一百零一条至第一百零九条正文。因拆条正则未识别，它们被合并进前一条；不能把对应精确条号“未命中”解释为没有相关法条，也不能把 1,062 推断为官方法典只有这些条款。

已修复**构建脚本**的条号识别和清理正则，加入“零/〇”；没有运行其 `main()` 重建全库，因为缺失的原 Markdown 尚未补齐。旧 JSON 仍为原样。修复前后其 SHA-256 都是：

`26acddc182e4ecaca66dc48380cd590b8c1a9c2cca177a652bcad01fa78e45ad`

只针对本法的标签分组问题获得了具体证据；未声称所有条文文字、日期、附件或其他 2,189 个法律版本已完成核验。另将旧 `search.py` 的 T1 输出从“核心·已确认”改为“核心·需核验”，避免没有核验日期却显示已确认。

## 5. 案例库 TLS 风险与最小处理

原文件：

`/Users/songmenglvshi/Documents/Codex/2026-06-25/wo-s/work/menglu-legal-treasury/sources/legal-tools/人民法院案例库MCP/scripts/client.py`

其第 45–46 行在存在 Token 时设置 `faxin-cpws-al-token` 请求头；第 50 行原为 `verify=False`。这会关闭证书验证，使连接无法按正常 TLS 规则确认服务端身份；若发生网络中间人攻击，登录 Token 与检索内容可能被截获或响应被替换。此为配置风险判断，并非发现已经泄露。[HTTPX 官方 TLS 说明](https://www.python-httpx.org/advanced/ssl/)明确解释默认验证与关闭验证的差别。

按授权仅改为 `verify=True`。本轮没有读取实际 Token，也没有调用已认证的案例接口。无凭证普通 GET `https://rmfyalk.court.gov.cn/` 返回 HTTP 200、TLS verify result=0；这只证明本机 curl 的公开首页连接可正常验签，不代表 HTTPX 认证请求或案例正文已验收。

若后续出现证书链错误，应记录具体错误并检查证书有效期、域名及受信 CA；确需额外 CA 时配置可信证书上下文。不要恢复为关闭验证，也不要把 HTTPX 与 curl 使用的信任库差异误判成必须关闭 TLS。

## 6. 修改、备份与运行态边界

备份目录：

`/Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review/verification/vendor-backup/2026-09-27-download-tls`

| 备份文件 | 原始 SHA-256 | 改动 |
| --- | --- | --- |
| `flk-server.py` | `5593604fc779472f0f3c3b03f1bb9237a8b538620babd9f098f097054343613e` | 原下载请求 `fileType` 改为 `format`，仅该行 |
| `rmfyalk-client.py` | `8dd768cb1c1594f86504755d153e5c4ee66fe0bd0567f2778cb03d6d26bfc38a` | `verify=False` 改 `True`，仅该行 |
| `china-build-index.py` | `b688c0a630df894f3d80a129b27727a34411dc9603de5efb8abdeb9f79dd01db` | 条号及条之序号的匹配/清理字符类补零/〇 |
| `china-search.py` | `9c0607334ff52edbb84dbd89656ea582fbb47ee197a504517c8297ad636958ea` | T1 显示为需核验，并纠正示例说明 |

回归文件：`tests/test_vendor_download.py`。4 项均先观察到相应失败，再经最小修改通过：下载参数、TLS 参数、含零条号拆分、T1 显示。它通过 AST/受控函数提取或安全的公共查询运行，避免导入案例服务器时加载 `.env`。另外在新进程加载实际国家库客户端和修复后的下载函数，成功得到官方下载 URL；结果只输出无签名地址。

**运行态纠正：** `config/mcp.local.json` 的 18061/18062 是旧 HTTP 配置，本轮 `lsof` 未发现两端口监听。当前 Codex 已注册的是两个 stdio 包装器：

- `/Users/songmenglvshi/Documents/萌律的专属智能体/tools/mcp_flk_npc_stdio.py`
- `/Users/songmenglvshi/Documents/萌律的专属智能体/tools/mcp_rmfyalk_stdio.py`

包装器加载的正是上述 treasury 的 `sources/legal-tools/.../scripts` 与 `.python-deps`。本轮没有停止任何服务，也没有重新连接当前会话的 MCP 进程；旧进程可能仍缓存修复前代码及客户端。修复对新进程有效，当前连接须重新建立后再验收，不能声称已热更新。

## 验收结论

已完成：参数根因复现、指定上游比较、单份官方原件下载和 CRC、段落文本抽取及来源哈希、漏零合并证据、4 项回归通过、4 份原代码备份、正常 TLS 配置落盘；主任务已将样本 TXT 加入隔离库，并验证漏拆条号可被检索。

仍未完成：当前会话 MCP 重新连接后的端到端验收、案例登录/正文验收、全库重新分条、法律全文完整性与适用性人工审核、正文数据库发布。本文不把这些事项称为已通过。
