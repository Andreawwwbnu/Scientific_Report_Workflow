---
来源编号: AIDB06
标题: Oracle AI Vector Search User's Guide
来源链接: https://docs.oracle.com/en/database/oracle/oracle-database/23/vecse/ai-vector-search-users-guide.pdf
发布主体: Oracle官方文档
发布时间: '2024'
文献类型: 企业级向量数据库官方技术指南
可信度等级: 高（Oracle官方定义，明确向量数据类型、混合查询标准与技术边界）
来源分类: 02-技术内涵与核心机理
核心对应章节: '2.1'
标签:
- Oracle AI
- 向量搜索
- 混合查询
- 企业级数据库
- 技术规范
专题: 面向AI的新型数据库技术（AI-Native Database）
抓取时间: '2026-08-31 15:23:23'
---

# AIDB06 Oracle AI Vector Search User's Guide

> ⚠️ **抓取状态：** 已通过人工补充。

Oracle AI Vector Search stores and indexes vector embeddings for fast retrieval and similarity search. 
• Overview of Oracle AI Vector Search Oracle AI Vector Search is designed for Artificial Intelligence (AI) workloads and allows you to query data based on semantics, rather than keywords. • Why Use Oracle AI Vector Search? One of the biggest benefits of Oracle AI Vector Search is that semantic search on unstructured data can be combined with relational search on business data in one single system. • Oracle AI Vector Search Workflow A typical Oracle AI Vector Search workflow follows the included primary steps. Overview of Oracle AI Vector Search Oracle AI Vector Search is designed for Artificial Intelligence (AI) workloads and allows you to query data based on semantics, rather than keywords. VECTOR Data Type The VECTOR data type is introduced with the release of Oracle AI Database 26ai, providing the foundation to store vector embeddings alongside business data in the database. Using embedding models, you can transform unstructured data into vector embeddings that can then be used for semantic queries on business data. In order to use the VECTOR data type and its related features, the COMPATIBLE initialization parameter must be set to 23.4.0 or higher. For more information about the parameter and how to change it, see Oracle AI Database Upgrade Guide. See the following basic example of using the VECTOR data type in a table definition: CREATE TABLE docs (doc_id INT, doc_text CLOB, doc_vector VECTOR); For more information about the VECTOR data type and how to use vectors in tables, see Create Tables Using the VECTOR Data Type. Due to the numerical nature of the VECTOR data type, you can use it as an input to the machine learning algorithms such as classification, anomaly, regression, clustering and feature extraction. More details on using VECTOR data type in machine learning could be found in Vector Data Type Support.