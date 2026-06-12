"""
知识冲突检测
替代 collision_detector.sh — 用 LLM 做语义冲突判断，不靠 emoji 解析

将新文章与已有 wiki/综述/踩坑对比，检测:
  🔄 冲突 — 新信息与已有结论矛盾
  ➕ 补充 — 新信息补充了已有结论
  ⚡ 替代 — 新信息提出了更优方案
"""
import json
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

from config import config, DEEPSEEK_API_KEY


def _call_llm(prompt: str) -> str:
    api_key = DEEPSEEK_API_KEY
    body = {
        "model": "deepseek-chat",
        "max_tokens": 1500,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
        choices = data.get("choices", [])
        return choices[0].get("message", {}).get("content", "") if choices else ""


class ContradictionDetector:
    def __init__(self):
        self.config = config

    def _load_knowledge_core(self, tag: str) -> str:
        """提取某个标签的知识库核心结论"""
        vault = Path(self.config["paths"]["obsidian_vault"])
        parts = []

        for dir_name in ("wiki", "curated/reviews", "pitfalls"):
            d = vault / dir_name
            if not d.exists():
                continue
            for md in list(d.glob("**/*.md"))[:30]:
                try:
                    content = md.read_text(encoding="utf-8")
                    if tag.lower() not in content.lower():
                        continue
                    lines = content.split("\n")
                    excerpt = "\n".join(lines[:80])
                    parts.append(f"--- {md.relative_to(vault)} ---\n{excerpt}")
                except Exception:
                    pass

        return "\n\n".join(parts[:4])

    def detect(self, tagged_file: str, date_str: str = None) -> list[dict]:
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        with open(tagged_file, "r", encoding="utf-8") as f:
            articles = json.load(f)

        relevant = [a for a in articles if a.get("core_content") and a.get("value_judgment")]
        if not relevant:
            return []

        findings = []
        for a in relevant[:5]:
            tech_tag = a.get("tech_tag", "").replace("#", "")
            knowledge = self._load_knowledge_core(tech_tag)
            if not knowledge:
                findings.append({"article": a["title"], "tag": tech_tag, "verdict": "no_baseline", "detail": "无知识基线"})
                continue

            new_info = f"标题: {a['title']}\n核心内容: {a.get('core_content', '')}\n价值判断: {a.get('value_judgment', '')}"

            prompt = f"""你是知识一致性检查员。对比新文章与已有知识库，判断关系。

已有知识库（节选）:
{knowledge[:3000]}

新文章:
{new_info}

输出 JSON:
{{
  "verdict": "conflict / supplement / replace / consistent",
  "detail": "一句话说明关系（30字以内）",
  "confidence": 0.0-1.0
}}

只输出 JSON。"""

            try:
                raw = _call_llm(prompt)
                parsed = json.loads(raw)
                findings.append({
                    "article": a["title"],
                    "tag": tech_tag,
                    "verdict": parsed.get("verdict", "unknown"),
                    "detail": parsed.get("detail", ""),
                    "confidence": parsed.get("confidence", 0.5),
                })
            except Exception:
                findings.append({"article": a["title"], "tag": tech_tag, "verdict": "error", "detail": "检测失败"})

        return findings


if __name__ == "__main__":
    cd = ContradictionDetector()
    date_str = datetime.now().strftime("%Y-%m-%d")
    tagged_file = f"D:/Claude code/获取信息/data/{date_str}_tagged.json"
    if Path(tagged_file).exists():
        findings = cd.detect(tagged_file)
        for f in findings:
            emoji = {"conflict": "🔄", "supplement": "➕", "replace": "⚡", "consistent": "✅"}.get(f["verdict"], "❓")
            print(f"  {emoji} [{f['tag']}] {f['article'][:60]}: {f['detail']} ({f.get('confidence', '?')})")
