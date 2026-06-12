"""
领域自适应摘要器 — 自动判断领域 + 三维通用摘要

每篇文章输出:
  domain:         agent / 营养 / 其他
  core_content:   这篇文章讲了什么 (50-100字)
  value_judgment: 可信度/趋势/证据强度 (50-80字)
  relevance_to_me: 为什么你需要知道 (30-50字)

目录即分类，不再打 tech_tag / maturity_tag。
"""
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

from config import config, DEEPSEEK_API_KEY


SUMMARIZER_PROMPT = """你是一个知识库摘要助手。读者背景：
- 全栈后端转 AI/Agent 开发，在维护个人 AI 助手"沈念"
- 在维护 Obsidian 知识库（三层索引 + 混合检索 + wiki 提炼）
- 关注 Agent 架构、RAG、MCP、LLM 工具调用，也关注营养健康

请为每篇文章输出以下内容（JSON 格式）：

{
  "articles": [
    {
      "id": 0,
      "domain": "agent / 其他",
      "core_content": "这篇文章讲了什么核心内容，不超过100字",
      "value_judgment": "可信度如何、处于什么阶段、有什么证据支撑，不超过80字",
      "relevance_to_me": "为什么你需要知道，对你有什么影响，不超过50字"
    }
  ]
}

规则：
- domain: 优先匹配已知领域（agent），都不匹配用"其他"
- core_content: 是提炼后的核心信息，不是标题翻译
- value_judgment: 关注信息可靠性、行业趋势阶段、数据来源质量
- relevance_to_me: 具体到你关心的事情（agent开发/知识库建设/个人效率），无关时说"不直接相关"
- 只输出 JSON，不要其他内容

文章列表：
"""


def _call_deepseek(prompt: str, config: dict) -> str:
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
    """主入口：领域判断 + 三维摘要"""

    article_text = ""
    for i, a in enumerate(articles):
        summary = (a.get("summary", "") or "")[:200]
        article_text += f"[{i}] {a['title']}\n"
        article_text += f"    来源: {a['source']} | points: {a.get('points', 0)}\n"
        if summary:
            article_text += f"    摘要: {summary}\n"
        article_text += "\n"

    prompt = SUMMARIZER_PROMPT + "\n" + article_text

    print(f"[2/3] 领域判断 + 三维摘要 ({len(articles)} 篇)...")
    raw_output = _call_deepseek(prompt, config)
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
        item = {**a}
        match = (
            next((r for r in results if str(r.get("id", -1)) == str(articles.index(a))), None)
            or next((r for r in results if r.get("title", "") == a.get("title", "")), None)
        )
        if match:
            item["domain"] = match.get("domain", "其他")
            item["core_content"] = match.get("core_content", "")
            item["value_judgment"] = match.get("value_judgment", "")
            item["relevance_to_me"] = match.get("relevance_to_me", "")
        else:
            item["domain"] = "其他"
            item["core_content"] = ""
            item["value_judgment"] = ""
            item["relevance_to_me"] = ""
        merged.append(item)

    print(f"  摘要完成: {len(merged)} 篇")
    # 打印领域分布
    from collections import Counter
    domain_counts = Counter(a["domain"] for a in merged)
    for d, c in domain_counts.items():
        print(f"    {d}: {c} 篇")

    return merged


def save_tagged(articles: list[dict], date_str: str = None):
    """兼容旧接口名 — 保存摘要结果"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    data_dir = Path(config["paths"]["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)

    tagged_file = data_dir / f"{date_str}_tagged.json"
    with open(tagged_file, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"  已保存: {tagged_file}")
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
