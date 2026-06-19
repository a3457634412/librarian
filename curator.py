"""
单 Agent 策展 — 读文章 → 搜 wiki → 读全文 → 判断 → 写

替代旧 curator.py + multi_agent_curation/ 三人小组。
每篇文章独立处理，写前护栏防重复。
"""
import json
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

from config import config, DEEPSEEK_API_KEY

VAULT = Path(config["paths"]["obsidian_vault"])
WIKI_ROOT = VAULT / "wiki"
AGENT_WIKI = WIKI_ROOT / "agent"


# ═══════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════

def _call_deepseek(prompt: str, max_tokens: int = 4096, temperature: float = 0.3,
                   json_mode: bool = False) -> str:
    body = {
        "model": "deepseek-chat",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    req = Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
    )
    with urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode())
        choices = data.get("choices", [])
        return choices[0].get("message", {}).get("content", "") if choices else ""


def _parse_json(text: str) -> dict | list | None:
    """4 层 JSON 解析兜底"""
    import re
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    m = re.search(r'```json\s*([\s\S]*?)\s*```', text)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    for m in re.finditer(r'```\s*([\s\S]*?)\s*```', text):
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            try:
                return json.loads(line)
            except (json.JSONDecodeError, TypeError):
                pass
    return None


def _get_wiki_index() -> list[dict]:
    """获取 agent wiki 目录下所有页面及标题"""
    if not AGENT_WIKI.exists():
        return []

    pages = []
    for md in sorted(AGENT_WIKI.glob("**/*.md")):
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


def _build_wiki_overview() -> str:
    """构建 wiki 目录概览"""
    from collections import defaultdict
    pages = _get_wiki_index()
    by_dir = defaultdict(list)
    for p in pages:
        parts = p["path"].replace("\\", "/").split("/")
        directory = "/".join(parts[:-1]) if len(parts) > 1 else "/"
        by_dir[directory].append((parts[-1], p["title"]))

    lines = ["## wiki/agent/ 目录结构\n"]
    for directory in sorted(by_dir):
        pages_in_dir = by_dir[directory]
        indent = "  " * (directory.count("/"))
        lines.append(f"- **{directory}/** ({len(pages_in_dir)} 页)")
        for filename, title in sorted(pages_in_dir):
            lines.append(f"  - `{filename}` — {title}")
    return "\n".join(lines)


def read_wiki_page(rel_path: str) -> str | None:
    """读取 wiki 页面全文"""
    if rel_path.startswith("wiki/"):
        rel_path = rel_path[5:]
    p = WIKI_ROOT / rel_path
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def write_wiki_page(rel_path: str, content: str) -> bool:
    """写入/更新 wiki 页面"""
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


def search_wiki(query: str, max_results: int = 5) -> list[dict]:
    """用 LLM 匹配查询到 wiki 页面，失败降级关键词"""
    pages = _get_wiki_index()
    if not pages:
        return []

    index_lines = []
    for p in pages:
        index_lines.append(f"- `{p['path']}` — {p['title']}")
    wiki_index = "\n".join(index_lines)

    SEARCH_PROMPT = f"""你是知识库搜索引擎。根据查询，从 wiki 页面列表中找到最相关的页面。

## wiki 页面列表

{wiki_index}

## 查询

{query}

## 任务

找出最相关的 {max_results} 个页面，按相关度从高到低排列。返回 JSON:
{{"results": [{{"path": "agent/架构/xxx.md", "reason": "..."}}]}}

规则: path 必须是列表中的真实路径，无相关页面时返回空数组，只输出 JSON。"""

    try:
        raw = _call_deepseek(SEARCH_PROMPT, max_tokens=500, temperature=0.1, json_mode=True)
        parsed = _parse_json(raw)
        if parsed and isinstance(parsed, dict):
            matched = parsed.get("results", [])
            results = []
            for item in matched:
                path = item.get("path", "")
                if not path:
                    continue
                content = read_wiki_page(path)
                snippet = content[:200] if content else ""
                results.append({"path": path, "snippet": snippet, "reason": item.get("reason", "")})
            if results:
                return results
    except Exception:
        pass

    # 关键词降级
    keywords = [kw.lower() for kw in query.split() if len(kw) > 1]
    if not keywords:
        return []

    scored = []
    for p in pages:
        path = p["path"]
        content = read_wiki_page(path)
        if not content:
            continue
        hits = sum(content.lower().count(kw) for kw in keywords)
        if hits > 0:
            scored.append({"path": path, "snippet": content[:200], "score": hits})
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    return scored[:max_results]


# ═══════════════════════════════════════════════
# 策展 Agent
# ═══════════════════════════════════════════════

CURATOR_PROMPT = """你是知识库策展人，维护一个 Agent 工程师的个人 wiki (Obsidian)。

## 知识库当前结构

__WIKI_OVERVIEW__

## 需要评估的文章

__ARTICLE__

## 搜索到的相关 wiki 页面

__SEARCH_RESULTS__

## 相关页面全文

__RELATED_PAGES__

## 你的任务

判断这篇文章对知识库的价值，输出决策 JSON:

{
  "decision": "merge",
  "target_page": "agent/架构/记忆架构.md",
  "insert_after": "## 长期记忆方案",
  "rationale": "补充 MemOS 与 LangMem 的对比数据",
  "content": "### MemOS\\n\\n- 核心思路: ...\\n- 与 LangMem 对比: ..."
}

决策类型:
- **merge**: 补充价值，追加到已有页面。优先选这个
- **create**: 全新方向，wiki 确定无覆盖。需谨慎
- **skip**: 已有覆盖 / 信息密度不足 / 纯新闻

写前护栏:
- 已有页面是否已覆盖此内容 >50%? → skip
- 目标页面最近是否被策展更新过（看 frontmatter 的 updated 日期，3天内更新过）? → skip，除非新信息确实重大且给出明确理由
- 新页面和已有页面是否有明显重叠? → merge 而非 create
- 不确定是否重复 → skip

内容硬规则:
- 描述外部项目/工具时，只写文章里明确提到的信息。不要推测实现原理、技术栈、编程语言。不确定的细节写"待确认"
- 正文里提到项目名、工具名、技术术语时，检查搜索结果里的 wiki 页面。如果已有对应页面 → 用 [[wikilink]] 包裹（如 [[检索/本地优先记忆层|ContextAtlas]]）。不要只在末尾放链接，正文里就要有
- 不要写"本文介绍了..."这种废话开头
- 每个断言有依据

只输出 JSON。"""


def curate_article(article: dict, wiki_overview: str) -> dict | None:
    """策展单篇文章。返回决策 dict 或 None"""
    title = article.get("title", "")
    core = article.get("core_content", "")
    values = article.get("value_judgment", "")

    search_query = f"{title} {core}"[:200]
    search_results = search_wiki(search_query, max_results=5)

    if not search_results:
        return {
            "title": title,
            "decision": "skip",
            "rationale": "无相关 wiki 页面",
        }

    # 读取相关页面全文
    related_pages_text = ""
    loaded = set()
    for sr in search_results[:3]:
        path = sr.get("path", "")
        if path in loaded:
            continue
        content = read_wiki_page(path)
        if content:
            related_pages_text += f"\n### {path}\n\n{content[:3000]}\n\n---\n"
            loaded.add(path)

    search_text = ""
    for sr in search_results[:5]:
        search_text += f"- `{sr['path']}` — {sr.get('reason', sr.get('snippet', '')[:80])}\n"

    article_text = f"""标题: {title}
URL: {article.get('url', '')}
💡 核心内容: {core}
🔮 趋势判断: {values}"""

    prompt = CURATOR_PROMPT\
        .replace("__WIKI_OVERVIEW__", wiki_overview)\
        .replace("__ARTICLE__", article_text)\
        .replace("__SEARCH_RESULTS__", search_text)\
        .replace("__RELATED_PAGES__", related_pages_text[:6000])

    try:
        raw = _call_deepseek(prompt, max_tokens=4000, temperature=0.2, json_mode=True)
        result = _parse_json(raw)
        if result and isinstance(result, dict) and "decision" in result:
            result["title"] = title
            return result
    except Exception as e:
        print(f"    ⚠️ 策展 LLM 调用失败: {e}")

    return None


class Curator:
    """单 Agent 策展器"""

    def __init__(self):
        self.log_dir = Path(config["paths"]["librarian_logs"]) / "curation"

    def curate(self, articles: list[dict], date_str: str) -> list[dict]:
        """策展入口 — 对每篇 agent 文章独立判断并写入"""
        if not articles:
            print("  无文章，跳过策展")
            return []

        wiki_overview = _build_wiki_overview()
        day_log_dir = self.log_dir / date_str
        day_log_dir.mkdir(parents=True, exist_ok=True)

        decisions = []
        written = 0
        skipped = 0
        failed = 0

        print(f"\n  策展 {len(articles)} 篇 agent 文章...")

        for a in articles:
            title = a.get("title", "")[:60]
            print(f"    📄 {title}...")
            result = curate_article(a, wiki_overview)

            if not result:
                decisions.append({"title": a.get("title", ""), "decision": "error", "rationale": "LLM 调用失败"})
                failed += 1
                continue

            decision = result.get("decision", "skip")
            print(f"       → {decision}")

            if decision == "skip":
                skipped += 1
                decisions.append(result)
                continue

            target = result.get("target_page", "")
            content_to_write = result.get("content", "")

            if not target or not content_to_write:
                result["status"] = "skipped"
                result["rationale"] = result.get("rationale", "") + " (无目标页面或内容)"
                skipped += 1
                decisions.append(result)
                continue

            if decision == "merge":
                current = read_wiki_page(target)
                if current:
                    insert_after = result.get("insert_after", "")
                    if insert_after and insert_after in current:
                        idx = current.find(insert_after)
                        next_section = current.find("\n## ", idx + len(insert_after))
                        if next_section == -1:
                            next_section = len(current)
                        updated = current[:next_section].rstrip() + "\n\n" + content_to_write + "\n" + current[next_section:]
                    elif "\n## 相关" in current:
                        idx = current.rfind("\n## 相关")
                        updated = current[:idx] + "\n" + content_to_write + "\n" + current[idx:]
                    else:
                        updated = current.rstrip() + "\n\n" + content_to_write + "\n"

                    if write_wiki_page(target, updated):
                        written += 1
                        result["status"] = "written"
                    else:
                        failed += 1
                        result["status"] = "write_failed"
                else:
                    if write_wiki_page(target, content_to_write):
                        written += 1
                        result["status"] = "written"
                    else:
                        failed += 1
                        result["status"] = "write_failed"

            elif decision == "create":
                if write_wiki_page(target, content_to_write):
                    written += 1
                    result["status"] = "written"
                else:
                    failed += 1
                    result["status"] = "write_failed"

            decisions.append(result)

        log_file = day_log_dir / "curation.json"
        log_file.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"  策展完成: {written} 写入, {skipped} 跳过, {failed} 失败")
        return decisions