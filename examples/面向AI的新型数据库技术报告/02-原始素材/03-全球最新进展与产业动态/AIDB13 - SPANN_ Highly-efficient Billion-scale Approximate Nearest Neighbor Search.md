---
来源编号: AIDB13
标题: 'SPANN: Highly-efficient Billion-scale Approximate Nearest Neighbor Search'
来源链接: https://arxiv.org/abs/2111.08566
发布主体: NeurIPS 2021 / arXiv
发布时间: 2021-11
文献类型: 十亿级混合向量索引技术论文
可信度等级: 高（微软研究院成果，内存-磁盘混合向量索引，十亿级规模性能标杆）
来源分类: 03-全球最新进展与产业动态
核心对应章节: '3.2'
标签:
- SPANN
- 向量索引
- 近似最近邻搜索
- 十亿级规模
- 混合存储
专题: 面向AI的新型数据库技术（AI-Native Database）
抓取时间: '2026-08-31 15:24:02'
作者: Qi Chen, Bing Zhao, Haidong Wang, Mingqin Li, Chuanjie Liu, Zengzhong Li, Mao
  Yang, Jingdong Wang
PDF链接: https://arxiv.org/pdf/2111.08566
---

# AIDB13 SPANN: Highly-efficient Billion-scale Approximate Nearest Neighbor Search

> **抓取状态：** 成功

**学科领域：** Databases (cs.DB) ; Artificial Intelligence (cs.AI); Computer Vision and Pattern Recognition (cs.CV); Information Retrieval (cs.IR); Machine Learning (cs.LG)

**作者：** Qi Chen, Bing Zhao, Haidong Wang, Mingqin Li, Chuanjie Liu, Zengzhong Li, Mao Yang, Jingdong Wang

**提交信息：** From: Jingdong Wang [ view email ] [v1] Fri, 5 Nov 2021 06:28:15 UTC (127 KB)

## Abstract

The in-memory algorithms for approximate nearest neighbor search (ANNS) have achieved great success for fast high-recall search, but are extremely expensive when handling very large scale database. Thus, there is an increasing request for the hybrid ANNS solutions with small memory and inexpensive solid-state drive (SSD). In this paper, we present a simple but efficient memory-disk hybrid indexing and search system, named SPANN, that follows the inverted index methodology. It stores the centroid points of the posting lists in the memory and the large posting lists in the disk. We guarantee both disk-access efficiency (low latency) and high recall by effectively reducing the disk-access number and retrieving high-quality posting lists. In the index-building stage, we adopt a hierarchical balanced clustering algorithm to balance the length of posting lists and augment the posting list by adding the points in the closure of the corresponding clusters. In the search stage, we use a query-aware scheme to dynamically prune the access of unnecessary posting lists. Experiment results demonstrate that SPANN is 2$\times$ faster than the state-of-the-art ANNS solution DiskANN to reach the same recall quality $90\%$ with same memory cost in three billion-scale datasets. It can reach $90\%$ recall@1 and recall@10 in just around one millisecond with only 32GB memory cost. Code is available at: {\footnotesize\color{blue}{\url{ this https URL }}}.
