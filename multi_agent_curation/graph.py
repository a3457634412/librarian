"""多 Agent 策展 — 三人小组编排

主线: Signal → Curation → Wiki → 写入
失败策略: 任何 Agent 异常直接抛出，外层 agent.py 回退旧策展逻辑
"""

from multi_agent_curation.state import CurationState
from multi_agent_curation.agents import signal_agent, curation_agent, wiki_agent
from multi_agent_curation.logger import save_summary


def run_curation_pipeline(articles: list[dict], date_str: str,
                          dry_run: bool = False) -> dict:
    """
    多 Agent 策展主入口。

    任何 Agent 失败 → 异常直接传播到 agent.py → 全量回退旧逻辑。
    不做逐层降级——要么三人小组完整跑通，要么全部回退。
    """
    if not articles:
        print("  [Multi-Agent] 无文章，跳过策展")
        return {"signals": [], "curation_plan": [], "wiki_updates": [], "errors": []}

    print(f"\n{'='*50}")
    print(f"  三人小组策展 — {date_str}")
    print(f"  文章: {len(articles)} 篇")
    print(f"{'='*50}")

    state = CurationState(articles, date_str)

    # ── Agent 1: Signal ──
    print("\n[1/3] Signal Agent — 提炼信号...")
    state = signal_agent(state)
    if not state.signals:
        print("  ⚠️ Signal Agent 无产出，策展终止")
        _save_and_return(state, date_str)
        return state.to_dict()

    # ── Agent 2: Curation ──
    print("\n[2/3] Curation Agent — 做策展方案...")
    state = curation_agent(state)
    if not state.curation_plan:
        print("  ⚠️ Curation Agent 无产出，策展终止")
        _save_and_return(state, date_str)
        return state.to_dict()

    decisions = [p.get("decision") for p in state.curation_plan]
    print(f"  决策分布: curate={decisions.count('curate')} "
          f"merge={decisions.count('merge')} skip={decisions.count('skip')} "
          f"schema_gap={decisions.count('schema_gap')}")

    # schema_gap 也算非实操决策，但单独提示
    gaps = [p for p in state.curation_plan if p.get("decision") == "schema_gap"]
    for g in gaps:
        suggested = g.get("suggested_directory", "?")
        print(f"  🔍 schema_gap: {g.get('signal', '')[:60]} → 建议新建 {suggested}")

    actionable = [p for p in state.curation_plan
                  if p.get("decision") not in ("skip", "schema_gap")]
    if not actionable:
        print("  → 无实操决策，跳过 Wiki Agent")
        _save_and_return(state, date_str)
        return state.to_dict()

    # ── Agent 3: Wiki ──
    if dry_run:
        print("\n[3/3] Wiki Agent — DRY RUN 模式，跳过写入")
    else:
        print("\n[3/3] Wiki Agent — 审方案 + 写 wiki...")
        state = wiki_agent(state)

    # ── 输出 ──
    print(f"\n{'='*50}")
    written = sum(1 for u in state.wiki_updates if u.get("status") == "written")
    approved = sum(1 for u in state.wiki_updates if u.get("approval") == "approved")
    rejected = sum(1 for u in state.wiki_updates if u.get("approval") == "rejected")
    print(f"  结果: {approved} 批准 ({written} 已写入), {rejected} 驳回")
    if state.errors:
        print(f"  ⚠️ {len(state.errors)} 个错误")
        for e in state.errors:
            print(f"    - {e}")
    print(f"{'='*50}")

    _save_and_return(state, date_str)
    return state.to_dict()


def _save_and_return(state: CurationState, date_str: str):
    try:
        summary_path = save_summary(date_str, state.to_dict())
        print(f"  日志: {summary_path}")
    except Exception as e:
        print(f"  ⚠️ 保存摘要失败: {e}")
