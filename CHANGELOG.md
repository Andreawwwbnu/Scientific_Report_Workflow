# Changelog

## 3.0.0

整体重构。核心目标：让报告里的每个论断都能追溯并被核验；让“换专题”只改配置；让仓库可复现、可测试。

### 流程与可信度
- **阶段 2 检索代替截断**：全文分块 + BM25，按小节任务取最相关片段（每源保底带文首块）；旧版每篇只保留首尾约 1.5k 字，arXiv 实际只有摘要。
- **证据可核验**：模型输出 JSON `{claim, quote, source, chunk}`，代码校验来源白名单、`quote` 是原文逐字子串、`claim` 数字出现在原文；不合格直接丢弃（旧版只做编号合法性告警）。
- **阶段 3 确定性处理**：引用限定在本小节证据来源；非法引用先带反馈重试，仍有则删除该要点；数字、长度同样带反馈重试。
- **阶段 4 分章生成**：只重写问题章；综述章最后写并参考其他章；摘要/结论单独生成；篇幅预算由 `word_count` + 各章 `weight` 推导（旧版 prompt 写死 2900 字，与配置 3500–3900 矛盾，必然触发重写）。
- **阶段 5 无条件由清单重建参考文献**（旧版仅当模型输出了“参考文献”节才覆盖）；新增 `references.only_cited / numbering / max_authors`。
- **阶段 gate**：每个阶段返回 `ok`，失败即停并返回非零退出码（旧版编排器不看返回值）；`--no-gate` 可强制继续。
- **新增质检**：数字核验、含数字无引用、引用分布，可选 LLM 句级核验；新增可选“审稿”阶段。
- 抓取：已有正文的素材**默认不覆盖**（旧版重跑会冲掉手工补充）；`local_file`；arXiv 优先抓全文（HTML → PDF）；失败条目汇总为人工补充清单。

### Prompt
- 外置到 `report_workflow/prompts/`，带版本号，专题目录可同名覆盖；产物头部记录 Prompt 版本。
- 专题内容（写作要点、角色、风格）从代码迁入 `project.yaml`（`report.chapters[].write_guide`、`draft.persona`、`draft.style_rules`）。
- 统一骨架；素材块声明“块内指令忽略”；规则编号与职责拆分；不再要求模型控制精确字数。

### 工程与仓库
- 专题目录化：`projects/<名称>/`；`root` 默认 `./output`（相对专题目录），去掉个人绝对路径。
- 统一 CLI：`report-wf validate | run | status | init`；配置校验在运行前执行。
- 并发调用 + 磁盘缓存 + 运行记录（模型、阶段耗时、token 用量）。
- Word：真实 Title/Heading 样式（导航窗格、目录）、页码、可选模板；参考文献悬挂缩进。
- 离线 `demo` 专题 + `MockLLM`；pytest 离线测试；GitHub Actions；`pyproject.toml`；LICENSE；README 重写；旧审计记录移入 `docs/history/`。

### 不兼容变更
- `config/` → `projects/<名称>/`；`report_blueprint` → `report.chapters`；`fetch.*_keep_head/tail` 移除（由 `retrieval.*` 取代）。
- 阶段 2 证据文件格式变化（每条带原文摘录）；v2 产物需重跑阶段 2 起。
- 入口 `python -m workflow.run_pipeline` → `report-wf run`。

### 未在沙箱联网验证的部分
真实 LLM 调用、网页/arXiv 抓取与 PDF 回退经代码审查与离线单测覆盖，但未在联网环境做端到端实跑；首次使用请先用 `--stages 1` 小批量验证。
