"""
轻量查询路由 — 判断查询是 broad（探索型）还是 specific（定位型）

broad → 优先返回综述/wiki，调高 core 层权重
specific → 优先返回具体文章，调高关键词权重
"""
import json
import re
from urllib.request import Request, urlopen

from config import DEEPSEEK_API_KEY


def _call_llm(prompt: str, max_tokens: int = 10) -> str:
    api_key = DEEPSEEK_API_KEY
    if not api_key:
        return "broad"  # 无 API key 时默认 broad

    body = {
        "model": "deepseek-chat",
        "max_tokens": max_tokens,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        req = Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip().lower()
    except Exception:
        pass
    return "broad"


def classify(query: str) -> str:
    """
    判断查询类型，返回 "broad" 或 "specific"。
    用 LLM 一句话分类，成本 ~10 token。
    LLM 不可用时降级为规则判断。
    """
    # 规则判断兜底（不调 LLM 时直接走这个）
    broad_signals = [
        "怎么做", "如何", "方案", "对比", "选型", "架构", "全景",
        "综述", "概况", "趋势", "方向", "路线", "how to", "overview",
        "comparison", "survey", "best practice",
    ]
    specific_signals = [
        "实现", "代码", "参数", "配置", "报错", "api", "具体",
        "怎么用", "怎么写", "implementation", "tutorial", "example",
        "代码示例", "源码",
    ]

    q = query.lower()
    broad_hits = sum(1 for s in broad_signals if s in q)
    specific_hits = sum(1 for s in specific_signals if s in q)

    if broad_hits > specific_hits:
        return "broad"
    if specific_hits > broad_hits:
        return "specific"

    # 规则判断不确定 → LLM
    prompt = f'''判断以下查询的类型，只输出 "broad" 或 "specific"（不要其他内容）：

查询: "{query}"

broad = 想了解全貌、方案对比、该怎么做
specific = 想找具体实现、某篇文章的细节、某个数值或参数'''

    result = _call_llm(prompt)
    if "specific" in result:
        return "specific"
    return "broad"


def weights_for(query_type: str) -> dict:
    """根据查询类型返回检索权重"""
    if query_type == "broad":
        return {
            "core_weight": 1.5,
            "recent_weight": 1.0,
            "archive_weight": 0.0,
            "keyword_weight": 0.3,
            "semantic_weight": 0.7,
        }
    else:
        return {
            "core_weight": 1.0,
            "recent_weight": 1.5,
            "archive_weight": 0.0,
            "keyword_weight": 0.5,
            "semantic_weight": 0.5,
        }
