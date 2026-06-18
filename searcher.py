"""
统一检索入口 — LLM 匹配 + 关键词降级

搜索结果按 综述 → wiki 知识 分层返回。
"""
import sys
import re
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from curator import search_wiki, read_wiki_page, _get_wiki_index
from search.router import classify
from search.keyword import match_and_score, rank


def search(query: str, top_n: int = 8) -> str:
    vault = Path(__file__).parent.parent.parent  # not used, kept for compat
    vault_path = "D:/obsidian/1"
    wiki_dir = Path(vault_path) / "wiki"

    q_type = classify(query)

    # LLM 匹配 wiki 页面
    llm_results = search_wiki(query, max_results=10)

    # 关键词作为补充 (搜全文，不依赖 index)
    kw_results = match_and_score(query, wiki_dir, top_n=20) if wiki_dir.exists() else []
    ranked = rank(kw_results)

    route_label = "综述优先" if q_type == "broad" else "精确匹配"
    lines = [f"**搜索**: {query}  [{route_label}]"]
    lines.append("")

    # 分层输出
    groups = defaultdict(list)
    seen_paths = set()

    # LLM 结果优先
    if llm_results:
        for r in llm_results:
            path = r.get("path", "")
            if path not in seen_paths:
                groups["wiki"].append(r)
                seen_paths.add(path)

    # 关键词补充 (去重)
    for r in ranked:
        title = r.get("title", "")
        file_path = r.get("path", "")
        if file_path not in seen_paths and title not in seen_paths:
            groups["keyword"].append(r)
            seen_paths.add(file_path)
            seen_paths.add(title)

    # 输出综述
    reviews = [g for g in groups.get("wiki", []) if "综述" in g.get("path", "") or "review" in g.get("path", "").lower()]
    if reviews:
        lines.append("## 📌 综述")
        lines.append("")
        for r in reviews[:2]:
            lines.append(f"**{r.get('path', '')}**  — {r.get('reason', '')}")
            lines.append("")

    # 输出 wiki
    wiki_items = [g for g in groups.get("wiki", []) if g not in reviews]
    if wiki_items:
        lines.append("## 📚 知识")
        lines.append("")
        for r in wiki_items[:6]:
            path = r.get("path", "")
            title = Path(path).stem if path else ""
            snippet = r.get("snippet", "")[:120]
            lines.append(f"- **{title}**  _{path}_")
            if snippet:
                lines.append(f"  {snippet}")
            lines.append("")

    # 关键词补充
    kw_items = groups.get("keyword", [])[:3]
    if kw_items:
        lines.append("## 🔍 关键词匹配")
        lines.append("")
        for r in kw_items:
            title = r.get("title", "")
            path = r.get("path", "")
            lines.append(f"- **{title}**  _{path}_")
            lines.append("")

    if not groups:
        lines.append("_未找到匹配结果_")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python searcher.py <查询词>")
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    print(search(query))