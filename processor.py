"""
处理引擎 — 标签统计 + 关联 + Claude 洞察 + 反向链接 + 推送内容生成
替代 process_new.sh 的核心逻辑
"""
import json
import re
from collections import Counter
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

from config import config, DEEPSEEK_API_KEY


def _call_llm(prompt: str, max_tokens: int = 1024) -> str:
    api_key = DEEPSEEK_API_KEY
    body = {
        "model": "deepseek-chat",
        "max_tokens": max_tokens,
        "temperature": 0.3,
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
        if choices:
            return choices[0].get("message", {}).get("content", "")
    return ""


class Processor:
    def __init__(self):
        self.config = config

    def tag_stats(self, tagged: list[dict]) -> dict:
        counts = Counter(a.get("tech_tag", "") for a in tagged)
        return dict(counts.most_common())

    def anomaly_check(self, current_stats: dict, date_str: str) -> list[str]:
        vault = Path(self.config["paths"]["obsidian_raw"])
        past_7 = []
        d = datetime.strptime(date_str, "%Y-%m-%d")
        for i in range(1, 8):
            day = (d - timedelta(days=i)).strftime("%Y-%m-%d")
            file = vault / f"{day}.md"
            if file.exists():
                past_7.append(file)

        if len(past_7) < 3:
            return []

        anomalies = []
        tag_avg = defaultdict(float)
        for f in past_7:
            content = f.read_text(encoding="utf-8")
            for tag in current_stats:
                tag_avg[tag] += content.count(tag)
        for tag in tag_avg:
            tag_avg[tag] /= len(past_7)

        for tag, today_count in current_stats.items():
            avg = tag_avg[tag]
            if avg > 0 and today_count > avg * 2:
                anomalies.append(f"📈 `{tag}` 今日 {today_count} 篇（7日均值 {avg:.1f}）")

        return anomalies

    def generate_insights(self, articles: list[dict]) -> str:
        """Claude 提炼每日要点（3-5 条）"""
        relevant = [a for a in articles if a.get("tech_summary")]
        if len(relevant) < 3:
            return ""

        items = ""
        for a in relevant[:15]:
            items += f"- [{a.get('tech_tag', '')}] {a['title']}\n"
            items += f"  {a.get('tech_summary', '')}\n"
            if a.get("trend_signal"):
                items += f"  趋势: {a['trend_signal']}\n"
            items += "\n"

        prompt = f"""基于今天 {len(articles)} 篇 AI 文章，提炼 3-5 条最重要的洞察。

格式要求：每条以 "🔥 **要点**: " 开头，后跟一句概括（50 字以内）。
只输出洞察，不要其他内容。

{items}"""

        try:
            result = _call_llm(prompt, max_tokens=800)
            if result:
                return result.strip()
        except Exception as e:
            print(f"  ⚠️ 洞察生成跳过: {e}")
        return ""

    def find_related(self, article: dict, vault_dir: Path, max_related: int = 2) -> list[str]:
        keywords = set()
        tech_tag = article.get("tech_tag", "").replace("#", "")
        if tech_tag:
            keywords.add(tech_tag)
        for field in ("tech_summary", "trend_signal"):
            text = article.get(field, "")
            words = re.findall(r'[a-zA-Z]{3,}', text)
            keywords.update(w.lower() for w in words)

        if not keywords:
            return []

        scores = Counter()
        for md_file in vault_dir.glob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue
            for kw in keywords:
                scores[md_file.stem] += content.lower().count(kw.lower())

        date_str = datetime.now().strftime("%Y-%m-%d")
        top = scores.most_common(max_related + 1)
        top = [(k, v) for k, v in top if k != date_str]
        return [f"[[{k}]]" for k, _ in top[:max_related]]

    def add_backlinks(self, article: dict, related_notes: list[str], vault_dir: Path):
        title = article.get("title", "")
        url = article.get("url", "")
        tech_tag = article.get("tech_tag", "")

        for rn in related_notes:
            note_name = rn.strip("[[").strip("]]")
            note_file = vault_dir / f"{note_name}.md"
            if not note_file.exists():
                continue

            content = note_file.read_text(encoding="utf-8")
            new_line = f"- 🔗 [{tech_tag}] [{title}]({url})"

            if "🔗 外部动态" in content:
                content = content.rstrip() + f"\n{new_line}\n"
            else:
                content = content.rstrip() + f"\n\n## 🔗 外部动态\n\n{new_line}\n"

            note_file.write_text(content, encoding="utf-8")

    def process(self, tagged_file: str, date_str: str = None):
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        config = self.config
        with open(tagged_file, "r", encoding="utf-8") as f:
            articles = json.load(f)

        stats = self.tag_stats(articles)
        anomalies = self.anomaly_check(stats, date_str)

        vault_dir = Path(config["paths"]["obsidian_raw"])
        relevant_articles = [a for a in articles if a.get("relevance") in ("#核心相关", "#可能与我的部署相关")]
        associations = []
        for a in relevant_articles[:10]:
            related = self.find_related(a, vault_dir)
            if related:
                associations.append({"article": a["title"], "related": related})
                self.add_backlinks(a, related, vault_dir)

        insights = self.generate_insights(articles)

        extended = self._build_extended_content(stats, anomalies, associations, insights, articles)
        return extended

    def _build_extended_content(self, stats, anomalies, associations, insights, articles):
        lines = ["", "---", "", "## 📊 标签统计", ""]
        for tag, count in stats.items():
            lines.append(f"- `{tag}`: {count} 篇")

        if anomalies:
            lines.extend(["", "## ⚠️ 异常检测", ""])
            lines.extend(f"- {a}" for a in anomalies)

        if insights:
            lines.extend(["", "## 🔥 每日洞察", ""])
            lines.append(insights)

        if associations:
            lines.extend(["", "## 🔗 关联笔记", ""])
            for assoc in associations:
                lines.append(f"- **{assoc['article']}** → {' · '.join(assoc['related'])}")

        relevant = [a for a in articles if a.get("relevance_to_me")]
        if relevant:
            lines.extend(["", "## 🎯 你可能关心", ""])
            for a in relevant[:5]:
                lines.append(f"- **{a['title']}** — {a['relevance_to_me']}")

        lines.append("")
        return "\n".join(lines)


if __name__ == "__main__":
    import sys
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    p = Processor()
    tagged_file = f"D:/Claude code/获取信息/data/{date_str}_tagged.json"
    if Path(tagged_file).exists():
        extended = p.process(tagged_file, date_str)
        print(extended)
    else:
        print(f"文件不存在: {tagged_file}")
