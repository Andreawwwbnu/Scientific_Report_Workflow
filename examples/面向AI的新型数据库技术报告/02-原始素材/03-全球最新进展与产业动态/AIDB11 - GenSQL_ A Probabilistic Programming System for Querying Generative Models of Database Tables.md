---
来源编号: AIDB11
标题: 'GenSQL: A Probabilistic Programming System for Querying Generative Models of
  Database Tables'
来源链接: https://arxiv.org/abs/2406.15652
发布主体: PLDI 2024 / arXiv
发布时间: 2024-06
文献类型: 生成式数据库概率编程系统论文
可信度等级: 高（MIT成果，实现数据库表生成式模型与SQL的概率编程融合）
来源分类: 03-全球最新进展与产业动态
核心对应章节: '3.1'
标签:
- GenSQL
- 生成式数据库
- 概率编程
- SQL扩展
- PLDI
专题: 面向AI的新型数据库技术（AI-Native Database）
抓取时间: '2026-08-31 15:23:56'
作者: Mathieu Huot, Matin Ghavami, Alexander K. Lew, Ulrich Schaechtle, Cameron E. Freer,
  Zane Shelby, Martin C. Rinard, Feras A. Saad, Vikash K. Mansinghka
PDF链接: https://arxiv.org/pdf/2406.15652
---

# AIDB11 GenSQL: A Probabilistic Programming System for Querying Generative Models of Database Tables

> **抓取状态：** 成功

**学科领域：** Programming Languages (cs.PL)

**作者：** Mathieu Huot, Matin Ghavami, Alexander K. Lew, Ulrich Schaechtle, Cameron E. Freer, Zane Shelby, Martin C. Rinard, Feras A. Saad, Vikash K. Mansinghka

**提交信息：** From: Mathieu Huot [ view email ] [v1] Fri, 21 Jun 2024 21:09:48 UTC (23,585 KB)

## Abstract

This article presents GenSQL, a probabilistic programming system for querying probabilistic generative models of database tables. By augmenting SQL with only a few key primitives for querying probabilistic models, GenSQL enables complex Bayesian inference workflows to be concisely implemented. GenSQL's query planner rests on a unified programmatic interface for interacting with probabilistic models of tabular data, which makes it possible to use models written in a variety of probabilistic programming languages that are tailored to specific workflows. Probabilistic models may be automatically learned via probabilistic program synthesis, hand-designed, or a combination of both. GenSQL is formalized using a novel type system and denotational semantics, which together enable us to establish proofs that precisely characterize its soundness guarantees. We evaluate our system on two case real-world studies -- an anomaly detection in clinical trials and conditional synthetic data generation for a virtual wet lab -- and show that GenSQL more accurately captures the complexity of the data as compared to common baselines. We also show that the declarative syntax in GenSQL is more concise and less error-prone as compared to several alternatives. Finally, GenSQL delivers a 1.7-6.8x speedup compared to its closest competitor on a representative benchmark set and runs in comparable time to hand-written code, in part due to its reusable optimizations and code specialization.
