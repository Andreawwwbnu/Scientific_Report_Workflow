# 专业调研报告生成工作流（可复用版 v2.0）

输入：Google 检索得到的**文献情报矩阵**（标题/链接/对应章节/情报价值）。
输出：带规范引用与参考文献的 **Word 调研报告**。
全流程六阶段，证据链可追溯、引用零越界、换专题只需改两个 YAML 配置、不动代码。

> 对原六脚本的逐行核验结论见 [`AUDIT.md`](./AUDIT.md)（5 处断链/错误级问题已全部修复）。

---

## 一、流水线总览

```
                     config/project.yaml            config/literature_manifest.yaml
                     （章节/规则/模型/排版）          （文献清单：唯一事实源）
                                        │
 ① s1_fetch       联网抓取 arXiv/网页 → 02-原始素材/*.md（YAML元数据+正文）+ 索引
 ② s2_structure   LLM 证据抽取/归类   → 03-结构化素材/（只抽取，不写作，带来源编号）
 ③ s3_analyze     LLM 分小节深度分析  → 04-分析产出/（只基于素材推理）
 ④ s4_draft       LLM 成稿            → 05-报告草稿/报告草稿_完整版.md（自动质检）
 ⑤ s5_finalize    规范化/参考文献/质检 → 06-终稿与参考文献/*_v1.0.md
 ⑥ s6_to_word     Markdown → Word     → 06-终稿与参考文献/*_v1.0.docx（数字上标、仿宋/TNR）
```

**反幻觉机制贯穿全链**：每阶段只允许使用 manifest 白名单内的来源编号；模型输出后机器校验编号合法性；
同篇异源（arXiv/OpenReview/HuggingFace）用 `alias_for` 归并；正文引用与参考文献自动一致性核对。

## 二、安装

```bash
pip install -r requirements.txt
cp .env.example .env        # 填入 DEEPSEEK_API_KEY（阶段2/3/4需要；阶段1/5/6不需要）
```

## 三、运行

```bash
# 全流程
python -m workflow.run_pipeline --config config/project.yaml --stage all

# 单步 / 多步（阶段名：fetch structure analyze draft finalize word）
python -m workflow.run_pipeline --config config/project.yaml --stage fetch
python -m workflow.run_pipeline --config config/project.yaml --stage draft,finalize,word

# 临时换输出目录
python -m workflow.run_pipeline --config config/project.yaml --root /path/to/out --stage word

# 阶段6也可单独指定输入输出
python -m workflow.s6_to_word --config config/project.yaml -i in.md -o out.docx
```

人工卡点建议：①之后核对抓取失败清单并手工补正文；②③之后各做一次人工事实校验；④之后看自动质检告警。

## 四、复用新专题（核心：零代码改动）

1. 复制 `config/` 目录为新专题配置目录。
2. 改 **`project.yaml`**：
   - `project`：专题名、报告标题、编号前缀（如换 `WP`，引用即变成 `[WP01]`）；
   - `chapters`：章/小节名称、每节的 `extract_rule`（阶段2归类约束）与 `analyze_task`（阶段3分析指令）；
   - `report_blueprint`：成稿的章节压缩结构（阶段4 prompt 与阶段5校验共用）；
   - 模型、篇幅、Word 字体按需调整。
3. 改 **`literature_manifest.yaml`**：逐条录入文献矩阵；同篇异源加 `alias_for`。
4. 依次跑六阶段。

### manifest 字段速查

| 字段 | 必填 | 说明 |
|---|---|---|
| id/title/url/publisher/date | 是 | 编号、标题、链接、主体、日期（年份用于参考文献） |
| lit_type/credibility/chapter/section | 是 | 类型、可信度（高/中/低）、归属章文件夹、对应小节号 |
| tags | 否 | 标签 |
| author | 否 | 留空时 arXiv 由阶段1自动回填；仍无则用 publisher 作为机构作者 |
| alias_for | 否 | 同篇异源时填主编号，自动归并不重复计数 |

## 五、目录与文件说明

```
research_report_workflow/
├── config/
│   ├── project.yaml              # 项目/章节/模型/篇幅/排版配置
│   └── literature_manifest.yaml  # 文献清单（唯一事实源）
├── workflow/
│   ├── common.py                 # 配置加载、路径、manifest视图、LLM客户端、引用/字数工具
│   ├── s1_fetch.py … s6_to_word.py
│   └── run_pipeline.py           # 编排器
├── tests/make_sample.py          # 离线自测（无需联网/API）
├── requirements.txt / .env.example
├── AUDIT.md / README.md
└── output/                       # 运行产物（六类目录自动生成）
```

## 六、常见问题

- **阶段1某条抓取失败**：OpenReview 等 JS 页面或被反爬时会生成占位 md，按其中"原始链接"手工补正文即可，不影响后续。
- **reasoner 报参数错误**：已在 `LLMClient` 自动剔除 temperature；若换用其他厂商推理模型出现同类问题，在 `_is_reasoner` 中补充模型名特征即可。
- **想换模型厂商**：`.env` 改 `DEEPSEEK_BASE_URL` 为任意 OpenAI 兼容端点，并改 `project.yaml` 的三个模型名。
- **正文角标与参考文献对不上**：阶段5会报"正文引用但参考文献缺失"；阶段6遇到缺映射会逐条告警，按提示回查阶段2/3的来源标注。
- **离线验证流水线尾部**：`python tests/make_sample.py` 用合成样本跑通阶段5/6并回读 docx 断言。
