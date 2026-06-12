"""
多 Agent 策展系统 — 替换 curator.py + wiki_updater.py 的策展决策链

三层 Agent 流水线:
  Signal Agent  → 从 tagged articles 提炼 3-5 个可策展信号
  Curation Agent → 先更新已有知识, 再判断新方向, 输出策展方案
  Wiki Agent     → 审方案 + 写 wiki

集成: agent.py process_incoming() 中通过 feature flag 切换
"""

from multi_agent_curation.graph import run_curation_pipeline
