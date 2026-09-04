"""ange-agent:自进化 CLI agent。

三大子系统:
- wiki    —— 自建知识引擎(Karpathy 方法论:raw/wiki/index/log,ingest/query/lint)
- skills  —— deepagents SkillsMiddleware,SKILL.md 说明书轨
- evolution —— 每轮异步复盘(信号)、双轨晋升、退役进 wiki、双版本回滚
"""

__version__ = "0.1.0"
