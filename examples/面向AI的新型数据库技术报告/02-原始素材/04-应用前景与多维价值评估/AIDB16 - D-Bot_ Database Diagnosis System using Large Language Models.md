---
来源编号: AIDB16
标题: 'D-Bot: Database Diagnosis System using Large Language Models'
来源链接: https://arxiv.org/abs/2312.01454
发布主体: arXiv / VLDB
发布时间: 2023-12
文献类型: 大模型驱动的数据库智能诊断系统论文
可信度等级: 高（提出基于LLM的数据库自动诊断框架，D-Bot系统）
来源分类: 04-应用前景与多维价值评估
核心对应章节: '4.3'
标签:
- D-Bot
- 数据库诊断
- 大语言模型
- 智能运维
- 自治数据库
专题: 面向AI的新型数据库技术（AI-Native Database）
抓取时间: '2026-08-31 15:24:15'
作者: Xuanhe Zhou, Guoliang Li, Zhaoyan Sun, Zhiyuan Liu, Weize Chen, Jianming Wu, Jiesi
  Liu, Ruohang Feng, Guoyang Zeng
PDF链接: https://arxiv.org/pdf/2312.01454
---

# AIDB16 D-Bot: Database Diagnosis System using Large Language Models

> **抓取状态：** 成功

**学科领域：** Databases (cs.DB) ; Artificial Intelligence (cs.AI); Computation and Language (cs.CL); Machine Learning (cs.LG)

**作者：** Xuanhe Zhou, Guoliang Li, Zhaoyan Sun, Zhiyuan Liu, Weize Chen, Jianming Wu, Jiesi Liu, Ruohang Feng, Guoyang Zeng

**提交信息：** From: Xuanhe Zhou [ view email ] [v1] Sun, 3 Dec 2023 16:58:10 UTC (29,492 KB) [v2] Wed, 6 Dec 2023 02:53:11 UTC (29,665 KB)

## Abstract

Database administrators (DBAs) play an important role in managing, maintaining and optimizing database systems. However, it is hard and tedious for DBAs to manage a large number of databases and give timely response (waiting for hours is intolerable in many online cases). In addition, existing empirical methods only support limited diagnosis scenarios, which are also labor-intensive to update the diagnosis rules for database version updates. Recently large language models (LLMs) have shown great potential in various fields. Thus, we propose D-Bot, an LLM-based database diagnosis system that can automatically acquire knowledge from diagnosis documents, and generate reasonable and well-founded diagnosis report (i.e., identifying the root causes and solutions) within acceptable time (e.g., under 10 minutes compared to hours by a DBA). The techniques in D-Bot include (i) offline knowledge extraction from documents, (ii) automatic prompt generation (e.g., knowledge matching, tool retrieval), (iii) root cause analysis using tree search algorithm, and (iv) collaborative mechanism for complex anomalies with multiple root causes. We verify D-Bot on real benchmarks (including 539 anomalies of six typical applications), and the results show that D-Bot can effectively analyze the root causes of unseen anomalies and significantly outperforms traditional methods and vanilla models like GPT-4.
