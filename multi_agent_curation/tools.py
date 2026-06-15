"""多 Agent 策展 — Agent 工具函数

Curation Agent 和 Wiki Agent 通过这些工具与 Obsidian 知识库交互。
"""

import json
from pathlib import Path

from multi_agent_curation.llm import call, parse_json
from config import config as app_config

VAULT = Path(app_config["paths"]["obsidian_vault"])
WIKI_ROOT = VAULT / "wiki"

SEARCH_PROMPT = """你是知识库搜索引擎。根据查询，从 wiki 页面列表中找到最相关的页面。

## wiki 页面列表

__WIKI_INDEX__

## 查询

__QUERY__

## 任务

找出最相关的 __MAX_RESULTS__ 个页面，按相关度从高到低排列。

返回 JSON:
```json
{"results": [{"path": "agent/架构/安全架构.md", "reason": "该页面讨论代码执行隔离，与查询直接相关"}]}
```

规则：
- path 必须是列表中真实存在的路径
- reason 一句话说明为什么匹配
- 无高度相关页面时返回空数组
- 只输出 JSON，不要其他内容"""


def read_wiki_page(rel_path: str) -> str | None:
    """读一个 wiki 页面全文。rel_path 如 'wiki/agent/架构/ReAct与变体.md'"""
    if rel_path.startswith("wiki/"):
        rel_path = rel_path[5:]
    p = WIKI_ROOT / rel_path
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def _llm_search_wiki(query: str, domain: str, max_results: int) -> list[dict] | None:
    """用 DeepSeek Chat 匹配查询到 wiki 页面。失败返回 None。"""
    pages = get_wiki_index(domain)
    if not pages:
        return None

    # 构建紧凑的页面列表（文件名 + 标题）
    index_lines = []
    for p in pages:
        index_lines.append(f"- `{p['path']}` — {p['title']}")
    wiki_index = "\n".join(index_lines)

    prompt = SEARCH_PROMPT\
        .replace("__WIKI_INDEX__", wiki_index)\
        .replace("__QUERY__", query)\
        .replace("__MAX_RESULTS__", str(max_results))

    raw = call(prompt, max_tokens=800, temperature=0.1, json_mode=True)
    parsed = parse_json(raw)
    if not parsed or not isinstance(parsed, dict):
        return None

    matched = parsed.get("results", [])
    if not matched:
        return None

    results = []
    for item in matched:
        path = item.get("path", "")
        if not path:
            continue
        content = read_wiki_page(path)
        title = Path(path).stem
        snippet = ""
        if content:
            for line in content.split("\n"):
                s = line.strip()
                if s.startswith("# ") and not s.startswith("# 📚"):
                    title = s.lstrip("# ").strip()
                    break
            snippet = content[:200]

        results.append({
            "path": path,
            "title": title,
            "snippet": snippet[:200],
            "score": 5.0 - len(results) * 0.5,
        })

    return results if results else None


def _keyword_search_wiki(query: str, domain: str, max_results: int) -> list[dict]:
    """关键词匹配 wiki 页面 — 降级方案"""
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


def search_wiki(query: str, domain: str = "agent", max_results: int = 10
                ) -> list[dict]:
    """搜索 wiki 页面。LLM 匹配优先，关键词降级。

    返回 [{path, title, snippet, score}]"""
    try:
        results = _llm_search_wiki(query, domain, max_results)
        if results:
            return results
    except Exception:
        pass

    return _keyword_search_wiki(query, domain, max_results)


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
