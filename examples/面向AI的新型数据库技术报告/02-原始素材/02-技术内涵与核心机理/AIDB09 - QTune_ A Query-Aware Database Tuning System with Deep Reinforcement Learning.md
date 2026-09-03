---
来源编号: AIDB09
标题: 'QTune: A Query-Aware Database Tuning System with Deep Reinforcement Learning'
来源链接: https://www.vldb.org/pvldb/vol12/p2118-li.pdf
发布主体: PVLDB
发布时间: '2019'
文献类型: 查询感知数据库调优技术论文
可信度等级: 高（提出基于深度强化学习的查询感知参数调优框架，QTune系统）
来源分类: 02-技术内涵与核心机理
核心对应章节: '2.3'
标签:
- 数据库调优
- 深度强化学习
- 查询感知
- QTune
- 参数优化
专题: 面向AI的新型数据库技术（AI-Native Database）
抓取时间: '2026-08-31 15:23:49'
---

# AIDB09 QTune: A Query-Aware Database Tuning System with Deep Reinforcement Learning

> ⚠️ **抓取状态：** 已通过人工补充。

ABSTRACT 
Database knob tuning is important to achieve high performance (e.g., high throughput and low latency). However, knob tuning is an NP-hard problem and existing methods have several limitations. First, DBAs cannot tune a lot of database instances on different environments (e.g., different database vendors). Second, traditional machine-learning methods either cannot find good configurations or rely on a lot of high-quality training examples which are rather hard to obtain. Third, they only support coarse-grained tuning (e.g., workload-level tuning) but cannot provide fine-grained tuning (e.g., query-level tuning). To address these problems, we propose a query-aware database tuning system QTune with a deep reinforcement learning (DRL) model, which can efficiently and effectively tune the database configurations. QTune first featurizes the SQL queries by considering rich features of the SQL queries. Then QTune feeds the query features into the DRL model to choose suitable configurations. We propose a Double-State Deep Deterministic Policy Gradient (DS-DDPG) model to enable query-aware database configuration tuning, which utilizes the actor-critic networks to tune the database configurations based on both the query vector and database states. QTune provides three database tuning granularities: querylevel, workload-level, and cluster-level tuning. We deployed our techniques onto three real database systems, and experimental results show that QTune achieves high performance and outperforms the state-of-the-art tuning methods.