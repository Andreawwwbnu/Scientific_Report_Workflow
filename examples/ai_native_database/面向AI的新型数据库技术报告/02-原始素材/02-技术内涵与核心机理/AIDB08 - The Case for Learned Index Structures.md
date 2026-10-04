---
来源编号: AIDB08
标题: The Case for Learned Index Structures
来源链接: https://doi.org/10.1145/3183713.3196909
发布主体: SIGMOD
发布时间: '2018'
文献类型: 学习索引奠基性论文
可信度等级: 高（开创数据库内核学习化范式，经典内核机理文献）
来源分类: 02-技术内涵与核心机理
核心对应章节: '2.2'
标签:
- 学习索引
- 数据库内核
- 机器学习
- 索引结构
专题: 面向AI的新型数据库技术（AI-Native Database）
抓取时间: '2026-08-31 15:23:44'
---

# AIDB08 The Case for Learned Index Structures

> ⚠️ **抓取状态：** 已通过人工补充。

## Abstract

Indexes are models: a \btree-Index can be seen as a model to map a key to the position of a record within a sorted array, a Hash-Index as a model to map a key to a position of a record within an unsorted array, and a BitMap-Index as a model to indicate if a data record exists or not. In this exploratory research paper, we start from this premise and posit that all existing index structures can be replaced with other types of models, including deep-learning models, which we term \em learned indexes. We theoretically analyze under which conditions learned indexes outperform traditional index structures and describe the main challenges in designing learned index structures. Our initial results show that our learned indexes can have significant advantages over traditional indexes. More importantly, we believe that the idea of replacing core components of a data management system through learned models has far reaching implications for future systems designs and that this work provides just a glimpse of what might be possible.