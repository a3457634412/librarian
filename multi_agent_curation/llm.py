"""多 Agent 策展 — 共享 LLM 调用"""
import json
import re
from urllib.request import Request, urlopen

from config import DEEPSEEK_API_KEY, config as app_config

MODEL = "deepseek-chat"


def call(prompt: str, max_tokens: int = 4096, temperature: float = 0.3,
         json_mode: bool = False) -> str:
    """调 DeepSeek API，返回原始文本"""
    body = {
        "model": MODEL,
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


def parse_json(text: str) -> dict | list | None:
    """4 层 JSON 解析兜底，和 tagger.py 同策略"""
    # 1. 直接解析
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # 2. ```json 代码块
    m = re.search(r'```json\s*([\s\S]*?)\s*```', text)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    # 3. 任意 ``` 代码块
    for m in re.finditer(r'```\s*([\s\S]*?)\s*```', text):
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    # 4. 行匹配 — 找第一个 JSON 结构
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            try:
                return json.loads(line)
            except (json.JSONDecodeError, TypeError):
                pass
    return None
