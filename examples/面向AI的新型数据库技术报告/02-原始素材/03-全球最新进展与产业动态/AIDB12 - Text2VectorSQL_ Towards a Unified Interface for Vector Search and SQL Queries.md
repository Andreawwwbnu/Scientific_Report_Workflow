---
来源编号: AIDB12
标题: 'Text2VectorSQL: Towards a Unified Interface for Vector Search and SQL Queries'
来源链接: https://arxiv.org/abs/2506.23071
发布主体: arXiv
发布时间: 2025-06
文献类型: 统一自然语言向量SQL查询技术论文
可信度等级: 高（提出Text2VectorSQL任务，打通自然语言到向量+关系混合查询）
来源分类: 03-全球最新进展与产业动态
核心对应章节: '3.2'
标签:
- Text2VectorSQL
- 向量搜索
- 自然语言查询
- 混合查询
- 统一接口
专题: 面向AI的新型数据库技术（AI-Native Database）
抓取时间: '2026-08-31 15:23:59'
作者: Zhengren Wang, Dongwen Yao, Bozhou Li, Dongsheng Ma, Bo Li, Zhiyu Li, Feiyu Xiong,
  Bin Cui, Linpeng Tang, Wentao Zhang
PDF链接: https://arxiv.org/pdf/2506.23071
---

# AIDB12 Text2VectorSQL: Towards a Unified Interface for Vector Search and SQL Queries

> **抓取状态：** 成功

**学科领域：** Computation and Language (cs.CL)

**作者：** Zhengren Wang, Dongwen Yao, Bozhou Li, Dongsheng Ma, Bo Li, Zhiyu Li, Feiyu Xiong, Bin Cui, Linpeng Tang, Wentao Zhang

**提交信息：** From: Zhengren Wang [ view email ] [v1] Sun, 29 Jun 2025 03:17:42 UTC (345 KB) [v2] Thu, 6 Nov 2025 14:14:37 UTC (3,016 KB)

## Abstract

The proliferation of unstructured data poses a fundamental challenge to traditional database interfaces. While Text-to-SQL has democratized access to structured data, it remains incapable of interpreting semantic or multi-modal queries. Concurrently, vector search has emerged as the de facto standard for querying unstructured data, but its integration with SQL-termed VectorSQL-still relies on manual query crafting and lacks standardized evaluation methodologies, creating a significant gap between its potential and practical application. To bridge this fundamental gap, we introduce and formalize Text2VectorSQL, a novel task to establish a unified natural language interface for seamlessly querying both structured and unstructured data. To catalyze research in this new domain, we present a comprehensive foundational ecosystem, including: (1) A scalable and robust pipeline for synthesizing high-quality Text-to-VectorSQL training data. (2) VectorSQLBench, the first large-scale, multi-faceted benchmark for this task, encompassing 12 distinct combinations across three database backends (SQLite, PostgreSQL, ClickHouse) and four data sources (BIRD, Spider, arXiv, Wikipedia). (3) Several novel evaluation metrics designed for more nuanced performance analysis. Extensive experiments not only confirm strong baseline performance with our trained models, but also reveal the recall degradation challenge: the integration of SQL filters with vector search can lead to more pronounced result omissions than in conventional filtered vector search. By defining the core task, delivering the essential data and evaluation infrastructure, and identifying key research challenges, our work lays the essential groundwork to build the next generation of unified and intelligent data interfaces. Our repository is available at this https URL .
