# ChatGPT 私有入口：接入状态与完成条件

2026-09-27核对官方文档。当前是个人非商业学习项目，不公开发布，不把本地资料整包上传知识库。

## 已具备与尚缺

- 本地MCP回环服务已实测，提供6个公开资料只读工具；没有任意文件读取、私有案件、任意网络代理或写库工具。
- Plugin/Skill源码包存在；这不等于ChatGPT账号已安装。
- 缺少用户所属Platform组织的实际 `tunnel_id`、运行密钥及对应ChatGPT工作区权限。此项不能下载代替，也不应在聊天中粘贴密钥。
- 没有开启公网监听或隧道，没有替用户创建收费资源。
- 官方客户端v0.0.15的两次下载均因速度极低超时；已保留.part并记录预期SHA256，未安装/执行。下载阻碍与账号授权阻碍是两件事，详见verification/tunnel-client-readiness.json。

## 推荐接入路线

采用OpenAI官方 Secure MCP Tunnel（私有连接），而非直接公开没有认证的localhost服务。官方方案由本机向OpenAI发起出站HTTPS连接，不需开放入站端口；工具返回内容仍会发送给OpenAI，不能说成“全程数据不出本机”。

来源：[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。

需要用户在自己的账号完成：

1. 在Platform隧道设置确认创建/使用权限，创建或选择隧道，并关联目标ChatGPT工作区。
2. 将运行密钥通过本机安全配置提供给客户端；不要写进Skill、Markdown、ZIP或对话记录。
3. 在支持的ChatGPT开发者模式中，Plugins新建私有连接，选择Tunnel并关联该隧道。账号实际入口和权限须现场验证。

本机侧随后将官方 `tunnel-client` 连接到 `http://127.0.0.1:18063/mcp`，执行doctor，再启用登录自动运行。隧道ID/密钥未具备时不写入假配置、不启动循环失败的服务。

## 真正通过的验收条件

- 从ChatGPT新对话列出共享工具，调用 `public_corpus_inventory`，计数与本机一致。
- 从ChatGPT检索民法典第三条，取得正确来源、哈希、未核验状态；不会把镜像提升为权威结论。
- 断开隧道后，ChatGPT明确报告不可达，而不是声称仍已查询。
- 重启客户端后恢复；检查访问只涉及公开法库，不涉及整个Obsidian vault。
- 私有入口成功不等于获得公开分发资格；另见[插件说明](https://learn.chatgpt.com/docs/plugins)。

当前上述ChatGPT端到端验收尚未执行，不标为完成。
