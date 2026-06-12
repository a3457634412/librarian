"""
混合检索融合
移植 hybrid_merge.py — 关键词 40% + 语义 60%
"""
from collections import defaultdict

from config import config


def merge(
    kw_results: list[dict],
    sem_results: list[tuple[str, float]],
    kw_weight: float = None,
    sem_weight: float = None,
) -> list[dict]:
    """合并关键词和语义结果"""
    kw_weight = kw_weight or config["hybrid"]["keyword_weight"]
    sem_weight = sem_weight or config["hybrid"]["semantic_weight"]

    # 归一化关键词分数
    kw_scores = {}
    if kw_results:
        kw_max = max(r["final_score"] for r in kw_results) or 1
        for r in kw_results:
            kw_scores[r["title"]] = r["final_score"] / kw_max

    # 合并
    merged = defaultdict(float)
    for title, score in kw_scores.items():
        merged[title] += score * kw_weight

    for aid, score in sem_results:
        merged[aid] += score * sem_weight

    sorted_results = sorted(merged.items(), key=lambda x: x[1], reverse=True)
    return [{"id": k, "hybrid_score": v} for k, v in sorted_results[:50]]
