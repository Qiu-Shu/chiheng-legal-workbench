---
name: menglu-legal-treasury
description: "Use this skill for Chinese mainland legal work under the name “萌律的法律宝典”: PRC statutes and regulations, People’s Court Case Database research, Chinese case-law/citation checks, enterprise due diligence connectors, CNIPA/SAMR-oriented research, and routing between local open-source MCP servers plus commercial MCP connectors such as 元典、北大法宝、天眼查. Trigger when the user asks for 中国大陆法律, 法规, 法条, 案例, 裁判文书, 类案检索, 企业尽调, 法律意见, 合同审查, or to use 萌律的法律宝典."
metadata:
  short-description: 中国大陆法律 MCP 检索与实务工作流
---

# 萌律的法律宝典

This skill routes Chinese mainland legal tasks through installed MCP resources and conservative lawyer-facing workflows. Treat all model output as a draft for lawyer review; always ground legal assertions in retrievable source text when the task is substantive.

## Installed Bundle

Windows 迁移副本：先读取[本机配置](references/configuration.md)，从实际安装目录的 `verification/install/state.json` 核对 target。共享法库位于 target 根，外部客户端在 `target/vendor/treasury`；文件存在不说明宿主已注册或账号已登录。

Read [references/mcp-catalog.md](references/mcp-catalog.md) when choosing a data source or explaining what is installed.

Read [references/configuration.md](references/configuration.md) when the user asks to connect, start, configure, or troubleshoot the MCP servers.

## Routing Rules

- **Shared local research**: use the existing `chiheng-legal` connection as a shared public-law service for all lawyer Skills, not just litigation review. Read [references/shared-library.md](references/shared-library.md) for its live tools and limitations. This deployment is for the user's personal noncommercial learning; do not infer public publishing or commercial deployment authorization.
- **Current statutes/regulations**: use 国家法律法规数据库 MCP first (`flk-npc`). It is the default for laws, regulations, judicial interpretations, effective dates, history, and downloadable official text.
- **People’s Court reference cases**: use 人民法院案例库 MCP (`rmfyalk`) when the task asks for 指导性案例、参考案例、裁判要点、关联法条, or 类案 from the official case database.
- **Commercial legal databases**: use 元典、北大法宝 only when credentials are configured or the user explicitly asks for those sources.
- **Enterprise due diligence**: use 天眼查/元典 enterprise data if credentials are configured; otherwise say that commercial credentials are needed and fall back to user-provided materials.
- **Local lawyer workflow packs**: 本包只带 china-law 必要镜像辅助脚本和 JSON；完整 china-law、claude-for-legal-horizon、agentic-china-lawyer 及商业连接未随包安装。另行确认真实可用后再调用。
- **Unverified or unavailable source**: label it clearly. Do not present model memory as verified Chinese law.

## Legal Output Requirements

For substantive legal research:

1. Identify the issue, jurisdiction, date sensitivity, and requested output.
2. Retrieve or request authoritative source text before giving final legal conclusions.
3. Cite source name, article/case identifier, and retrieval source whenever available.
4. Separate “法律依据”, “案例/裁判口径”, “分析”, and “待核验/需补充材料”.
5. Do not invent article numbers, case names, document numbers, courts, dates, or database hits.

## 案例核验硬约束

不能核验就不准硬编：

1. 严禁虚构、猜测、拼接或补全案号、法院、观点和链接。
2. 每个已核验案例必须提供原文链接和裁判观点定位。
3. 只有二手摘要或无法打开原文的，只能列为待核验线索。
4. 没有找到可核验案例时，直接写 0 个，不得为了数量凑案例。
5. 输出前自检案号、法院、日期、观点和来源是否一致。

## Secrets

Never write API keys, tokens, cookies, or account credentials into this skill. Windows 案例认证只通过实际安装的 `.venv-mcp1/Scripts/python.exe windows_case_access.py --save-local` 隐藏输入，保存至唯一 `private/case-access.env`。不得从环境变量、vendor .env 或旧 Mac 凭据回退；按[本机配置](references/configuration.md)核验。
