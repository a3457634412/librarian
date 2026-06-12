"""
统一检索入口 — 分层返回：综述 → wiki 知识 → raw 原始

含轻量路由: broad → 优先综述/wiki, specific → 优先具体文章
"""
import sys
import re
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import config
from search.keyword import match_and_score, rank
from search.semantic import SemanticSearcher
from search.hybrid import merge
from search.router import classify, weights_for


def _classify_result(mid: str) -> tuple[str, str]:
    """
    ID 有两种格式:
      type::relpath::heading  (语义) → wiki::wiki/agent/... 或 raw::raw/agent/...
      纯标题                   (关键词) → "MemTensor/MemOS"
    """
    if "综述" in mid or "review" in mid.lower():
        return ("review", "📌 综述")
    if mid.startswith("wiki::"):
        return ("wiki", "📚 知识")
    if mid.startswith("raw::"):
        if "/手动/" in mid:
            return ("manual", "✏️ 手动投喂")
        return ("raw", "📄 原始文章")
    # 纯标题 → 可能是 wiki 段落或 raw 文章标题
    # 默认当知识返回（关键词匹配大概率命中 wiki）
    return ("wiki", "📚 知识")


def _extract_date(mid: str) -> str:
    # raw::raw/agent/每日/2026-05-30.md::MemOS → 2026-05-30
    m = re.search(r'(\d{4}-\d{2}-\d{2})', mid)
    return m.group(1) if m else ""


def _extract_info(mid: str) -> tuple[str, str]:
    """
    从 ID 提取 (显示标题, 来源路径)
    ID 格式: type::relpath::heading
    """
    parts = mid.split("::") if "::" in mid else [mid]
    heading = parts[-1] if parts else ""
    path = parts[-2] if len(parts) > 2 else ""

    if heading.isdigit():
        # 数字索引 → 用文件名
        fname = path.split("/")[-1].replace(".md", "") if path else ""
        return fname if fname else heading, path

    return heading, path


def search(query: str, top_n: int = 8) -> str:
    vault = Path(config["paths"]["obsidian_vault"])

    # ── 轻量路由 ──
    q_type = classify(query)
    w = weights_for(q_type)

    # ── 关键词：只搜 wiki（raw 已被提炼到 wiki，不需要重复搜）──
    wiki_dir = vault / "wiki"
    kw_results = match_and_score(query, wiki_dir, top_n=20) if wiki_dir.exists() else []
    ranked = rank(kw_results)

    # ── 语义 ──
    semantic = SemanticSearcher(
        core_weight=w["core_weight"],
        recent_weight=w["recent_weight"],
    )
    sem_results = semantic.search(query, top_n=50)

    # ── 混合 ──
    if sem_results:
        merged = merge(ranked, sem_results,
                       kw_weight=w["keyword_weight"],
                       sem_weight=w["semantic_weight"])
    else:
        merged = [{"id": r.get("title", ""), "hybrid_score": r.get("final_score", 0)}
                  for r in ranked]

    # ── 分层输出 ──
    route_label = "综述优先" if q_type == "broad" else "精确匹配"
    lines = [f"**搜索**: {query}  [{route_label}]"]
    lines.append("")

    # 知识边界
    if sem_results:
        max_sem = max(s[1] for s in sem_results)
        if max_sem < 0.3:
            lines.append(f"⚠️ 知识库覆盖范围有限，最高语义相关度 {max_sem:.2f}")
            lines.append("")

    # 分类 + 每层独立排序
    groups = defaultdict(list)
    for m in merged:
        cat, _ = _classify_result(m["id"])
        groups[cat].append(m)
    for cat in groups:
        groups[cat].sort(key=lambda x: x.get("hybrid_score", 0), reverse=True)

    display_order = ["review", "wiki", "manual"]
    output_count = 0
    # 每层最多显示数 (raw 不返回——已被提炼到 wiki)
    max_per_cat = {"review": 2, "wiki": 6, "manual": 2}

    for cat in display_order:
        items = groups.get(cat, [])
        if not items:
            continue

        labels = {
            "review": "📌 综述",
            "wiki": "📚 知识",
            "manual": "✏️ 手动投喂",
            "raw": "📄 原始文章",
        }
        lines.append(f"## {labels.get(cat, cat)}")
        lines.append("")

        seen_files = set()
        cat_count = 0
        for m in items:
            if output_count >= top_n or cat_count >= max_per_cat.get(cat, 5):
                break
            mid = m["id"]
            title, path = _extract_info(mid)
            score = m.get("hybrid_score", 0)

            # wiki/review 按文件去重，raw 按标题去重
            if cat in ("review", "wiki"):
                file_key = path
            else:
                file_key = title
            if file_key in seen_files:
                continue
            seen_files.add(file_key)

            if cat == "review":
                lines.append(f"**{title}**  [{path}]  (score: {score:.2f})")
                lines.append("")
            elif cat == "wiki":
                lines.append(f"- **{title}**  _{path}_")
                lines.append("")
            else:
                date = _extract_date(mid)
                lines.append(f"{output_count+1}. **{title}**  ({date})  [score: {score:.2f}]")
                lines.append("")

            output_count += 1
            cat_count += 1

        if output_count >= top_n:
            break

    if output_count == 0:
        lines.append("_未找到匹配结果_")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python searcher.py <查询词>")
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    print(search(query))
