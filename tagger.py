"""
文章过滤器 + 摘要 — 只判断是不是 agent 领域，输出核心内容 + 可信度

输出:
  domain:         agent / 其他 (非 agent 丢弃)
  core_content:   文章讲了什么 (50-100字)
  value_judgment: 可信度/趋势阶段/证据强度 (50-80字)
"""
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

from config import config, DEEPSEEK_API_KEY


SUMMARIZER_PROMPT = """你是知识库过滤器。只关注 Agent/LLM 领域的文章。

Agent 领域范围: Agent 架构、LLM 工具调用、MCP/A2A 协议、RAG/检索增强、多 Agent 协作、Agent 评估/观测、记忆系统、推理/规划、LLM 工程化。

对每篇文章输出 JSON:

{
  "articles": [
    {
      "id": 0,
      "domain": "agent",
      "core_content": "核心内容，不超过100字",
      "value_judgment": "可信度/趋势阶段/证据强度，不超过80字"
    }
  ]
}

规则:
- domain: 只输出 "agent" 或 "其他"
- core_content: 提炼后的核心信息，不是标题翻译
- value_judgment: 关注信息可靠性、行业趋势阶段、数据来源质量
- 只输出 JSON，不要其他内容

文章列表：
"""


def _call_deepseek(prompt: str) -> str:
    api_key = DEEPSEEK_API_KEY
    body = {
        "model": config["summarizer"]["model"],
        "max_tokens": config["summarizer"]["max_tokens"],
        "temperature": config["summarizer"]["temperature"],
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }
    req = Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urlopen(req, timeout=config["summarizer"]["timeout_seconds"]) as resp:
        data = json.loads(resp.read().decode())
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
    return ""


def _parse_response(text: str) -> list[dict]:
    """4 层 JSON 解析兜底"""
    try:
        data = json.loads(text)
        return data.get("articles", [])
    except (json.JSONDecodeError, KeyError):
        pass
    m = re.search(r'```json\s*([\s\S]*?)\s*```', text)
    if m:
        try:
            return json.loads(m.group(1)).get("articles", [])
        except (json.JSONDecodeError, KeyError):
            pass
    for m in re.finditer(r'```\s*([\s\S]*?)\s*```', text):
        try:
            return json.loads(m.group(1)).get("articles", [])
        except (json.JSONDecodeError, KeyError):
            pass
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith('{"articles"'):
            try:
                return json.loads(line).get("articles", [])
            except (json.JSONDecodeError, KeyError):
                pass
    return []


def summarize(articles: list[dict]) -> list[dict]:
    """主入口：领域判断 + 摘要 + 过滤非 agent"""

    article_text = ""
    for i, a in enumerate(articles):
        summary = (a.get("summary", "") or "")[:200]
        article_text += f"[{i}] {a['title']}\n"
        article_text += f"    来源: {a['source']} | points: {a.get('points', 0)}\n"
        if summary:
            article_text += f"    摘要: {summary}\n"
        article_text += "\n"

    prompt = SUMMARIZER_PROMPT + "\n" + article_text

    print(f"  LLM 过滤 + 摘要 ({len(articles)} 篇)...")
    raw_output = _call_deepseek(prompt)
    results = _parse_response(raw_output)

    if not results:
        print("  ⚠️ 4 层解析全部失败")
        data_dir = Path(config["paths"]["data_dir"])
        with open(data_dir / f"{datetime.now().strftime('%Y-%m-%d')}_raw_output.txt", "w", encoding="utf-8") as f:
            f.write(raw_output)
        return []

    # 合并结果
    merged = []
    for a in articles:
        idx = articles.index(a)
        match = (
            next((r for r in results if str(r.get("id", -1)) == str(idx)), None)
            or next((r for r in results if r.get("title", "") == a.get("title", "")), None)
        )
        item = {**a}
        if match:
            item["domain"] = match.get("domain", "其他")
            item["core_content"] = match.get("core_content", "")
            item["value_judgment"] = match.get("value_judgment", "")
        else:
            item["domain"] = "其他"
            item["core_content"] = ""
            item["value_judgment"] = ""
        merged.append(item)

    # 只保留 agent 领域
    agent_articles = [a for a in merged if a.get("domain") == "agent"]
    skipped = len(merged) - len(agent_articles)
    print(f"  agent: {len(agent_articles)} 篇, 丢弃: {skipped} 篇")

    return agent_articles


def save_tagged(articles: list[dict], date_str: str = None):
    """保存过滤后的结果到 tagged JSON"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    data_dir = Path(config["paths"]["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)

    tagged_file = data_dir / f"{date_str}_tagged.json"
    with open(tagged_file, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"  已保存: {tagged_file} ({len(articles)} 篇)")
    return tagged_file


# 兼容旧调用
def tag_articles(articles: list[dict]) -> list[dict]:
    return summarize(articles)


if __name__ == "__main__":
    import sys
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    data_dir = Path(config["paths"]["data_dir"])
    raw_file = data_dir / f"{date_str}_raw.json"

    with open(raw_file, "r", encoding="utf-8") as f:
        articles = json.load(f)

    tagged = summarize(articles)
    if tagged:
        save_tagged(tagged, date_str)