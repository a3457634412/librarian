"""多 Agent 策展 — Agent 工具函数

Curation Agent 和 Wiki Agent 通过这些工具与 Obsidian 知识库交互。
工具不调 LLM，是纯 Python 操作。
"""

import json
import re
from pathlib import Path
from collections import Counter

from config import config as app_config

VAULT = Path(app_config["paths"]["obsidian_vault"])
WIKI_ROOT = VAULT / "wiki"


def read_wiki_page(rel_path: str) -> str | None:
    """读一个 wiki 页面全文。rel_path 如 'wiki/agent/架构/ReAct与变体.md'"""
    if rel_path.startswith("wiki/"):
        rel_path = rel_path[5:]
    p = WIKI_ROOT / rel_path
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def search_wiki(query: str, domain: str = "agent", max_results: int = 10
                ) -> list[dict]:
    """关键词搜索 wiki 页面。返回 [{path, title, snippet, score}]"""
    keywords = [kw.lower() for kw in query.split() if len(kw) > 1]
    if not keywords:
        return []

    domain_root = WIKI_ROOT / domain
    if not domain_root.exists():
        return []

    scored = []
    for md in domain_root.glob("**/*.md"):
        try:
            content = md.read_text(encoding="utf-8")
        except Exception:
            continue
        text = content.lower()
        hits = sum(text.count(kw) for kw in keywords)
        if hits > 0:
            rel = str(md.relative_to(WIKI_ROOT))
            title = md.stem
            # 提取匹配行作为 snippet
            snippet = ""
            for line in content.split("\n"):
                if any(kw in line.lower() for kw in keywords):
                    snippet = line.strip()[:200]
                    break
            scored.append({
                "path": rel,
                "title": title,
                "snippet": snippet,
                "score": hits,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:max_results]


def write_wiki_page(rel_path: str, content: str) -> bool:
    """写入/更新 wiki 页面。rel_path 如 'wiki/agent/可靠性方案对比.md'"""
    if rel_path.startswith("wiki/"):
        rel_path = rel_path[5:]
    p = WIKI_ROOT / rel_path

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        print(f"  ⚠️ write_wiki_page 失败: {rel_path} — {e}")
        return False


def get_wiki_index(domain: str = "agent") -> list[dict]:
    """获取某领域 wiki 目录下所有页面及其标题"""
    domain_root = WIKI_ROOT / domain
    if not domain_root.exists():
        return []

    pages = []
    for md in sorted(domain_root.glob("**/*.md")):
        rel = str(md.relative_to(WIKI_ROOT))
        content = md.read_text(encoding="utf-8")
        # 提取第一个 # 标题（不含 frontmatter 内的）
        title = md.stem
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("# 📚"):
                title = stripped[2:].strip()
                break
        pages.append({"path": rel, "title": title})
    return pages


def get_wiki_frontmatter_tags(domain: str = "agent") -> dict[str, list[str]]:
    """获取某领域所有 wiki 页面的 frontmatter tags"""
    domain_root = WIKI_ROOT / domain
    if not domain_root.exists():
        return {}

    result = {}
    for md in domain_root.glob("**/*.md"):
        rel = str(md.relative_to(WIKI_ROOT))
        try:
            content = md.read_text(encoding="utf-8")
        except Exception:
            continue
        tags = []
        if content.startswith("---"):
            end = content.find("---", 3)
            if end > 0:
                fm = content[3:end]
                for line in fm.split("\n"):
                    line = line.strip()
                    if line.startswith("tags:"):
                        tag_str = line[5:].strip()
                        tags = [t.strip().strip("'\"") for t in tag_str.strip("[]").split(",")]
                        break
        result[rel] = tags
    return result
