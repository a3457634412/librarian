"""
策展引擎 — 按领域触发，LLM 生成综述 → 写入 wiki/{domain}/综述.md

三层触发: 常规（≥15篇+≥14天）+ 连续活跃（≥3天+≥8篇+≥7天）+ 内容信号
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from urllib.request import Request, urlopen

from config import config, DEEPSEEK_API_KEY


def _call_llm(prompt: str, max_tokens: int = 3000) -> str:
    api_key = DEEPSEEK_API_KEY
    body = {
        "model": "deepseek-chat",
        "max_tokens": max_tokens,
        "temperature": 0.4,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode())
        choices = data.get("choices", [])
        return choices[0].get("message", {}).get("content", "") if choices else ""


class Curator:
    def __init__(self):
        self.config = config

    def _domain_article_count(self, domain: str, raw_base: Path) -> int:
        domain_dir = raw_base / domain / "每日"
        if not domain_dir.exists():
            return 0
        count = 0
        for md in domain_dir.glob("*.md"):
            content = md.read_text(encoding="utf-8")
            count += content.count("***")
        return count

    def _domain_days(self, domain: str, raw_base: Path) -> set:
        domain_dir = raw_base / domain / "每日"
        if not domain_dir.exists():
            return set()
        return {md.stem for md in domain_dir.glob("*.md")}

    def _last_curation(self, domain: str) -> datetime | None:
        manifest_file = Path(self.config["paths"]["librarian_dir"]) / "curated" / "manifest.json"
        if manifest_file.exists():
            manifest = json.loads(manifest_file.read_text())
            if domain in manifest:
                dt_str = manifest[domain].get("last_curated", "")
                if dt_str:
                    return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).replace(tzinfo=None)
        return None

    def check_thresholds(self, date_str: str) -> list[str]:
        cfg = self.config["curation"]
        raw_base = Path(self.config["paths"]["obsidian_raw"])
        domains = self.config["summarizer"]["domains"]
        today = datetime.strptime(date_str, "%Y-%m-%d")

        triggered = []
        for domain in domains:
            count = self._domain_article_count(domain, raw_base)
            if count == 0:
                continue

            last = self._last_curation(domain)

            if count >= cfg["min_articles"]:
                if last is None or (today - last).days >= cfg["refresh_days"]:
                    triggered.append(domain)
                    continue

            days = self._domain_days(domain, raw_base)
            consecutive = 0
            for i in range(7):
                d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
                if d in days:
                    consecutive += 1
                else:
                    break
            if consecutive >= cfg["consecutive_min_days"] and count >= cfg["consecutive_min_count"]:
                if last is None or (today - last).days >= cfg["consecutive_refresh_days"]:
                    triggered.append(domain)

        return triggered

    def _collect_articles(self, domain: str, raw_base: Path) -> list[dict]:
        articles = []
        domain_dir = raw_base / domain / "每日"
        if not domain_dir.exists():
            return articles
        for md in sorted(domain_dir.glob("*.md")):
            content = md.read_text(encoding="utf-8")
            blocks = content.split("***")
            for block in blocks:
                title = ""
                core = ""
                val = ""
                for line in block.split("\n"):
                    if line.startswith("## "):
                        title = line[3:].strip()
                    elif line.startswith("💡 "):
                        core = line[2:].strip()
                    elif line.startswith("🔮 "):
                        val = line[2:].strip()
                if title:
                    articles.append({"date": md.stem, "title": title, "core": core, "value": val})
        return articles

    def curate(self, domain: str, date_str: str):
        cfg = self.config["curation"]
        raw_base = Path(self.config["paths"]["obsidian_raw"])
        wiki_domain = Path(self.config["paths"]["obsidian_wiki"]) / domain
        wiki_domain.mkdir(parents=True, exist_ok=True)

        articles = self._collect_articles(domain, raw_base)
        print(f"  策展 `{domain}`: {len(articles)} 篇文章")

        output_file = wiki_domain / "综述.md"

        article_text = ""
        for a in articles[-30:]:
            article_text += f"- [{a['date']}] {a['title']}\n"
            if a["core"]:
                article_text += f"  💡 {a['core'][:200]}\n"
            if a["value"]:
                article_text += f"  🔮 {a['value'][:150]}\n"

        prompt = f"""你是 AI 技术趋势分析助手。基于以下 {len(articles)} 篇关于 `{domain}` 领域的文章，生成一篇 800-1500 字的策展综述。

格式要求:
- 开头: 一句话概述该领域当前状态
- 子方向: 2-4 个正在形成的子方向
- 高频项目: 出现 ≥2 次的项目或技术
- 趋势观察: 领域在往什么方向演进
- 知识盲区: 这些文章没覆盖但重要的方面

文章列表:
{article_text[:5000]}

输出 Markdown 格式的综述正文，不要 frontmatter。"""

        try:
            body = _call_llm(prompt)
        except Exception as e:
            print(f"  ⚠️ LLM 调用失败: {e}")
            body = "_综述正文生成失败，请稍后手动触发策展。_"

        header = f"""---
domain: "{domain}"
date: {date_str}
article_count: {len(articles)}
type: review
---

# {domain} 策展综述

> 基于 {len(articles)} 篇文章，{date_str} 生成

{body}

---

## 文章列表

"""
        lines = [header]
        for a in articles[-30:]:
            lines.append(f"- **[{a['date']}]** {a['title']}")

        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        # 更新 manifest
        manifest_file = Path(self.config["paths"]["librarian_dir"]) / "curated" / "manifest.json"
        manifest = {}
        if manifest_file.exists():
            manifest = json.loads(manifest_file.read_text())

        manifest[domain] = {
            "last_curated": datetime.now().isoformat(),
            "article_count": len(articles),
            "output": str(output_file),
        }
        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        print(f"  已保存: {output_file}")
        return str(output_file)


if __name__ == "__main__":
    import sys
    c = Curator()
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")

    triggered = c.check_thresholds(date_str)
    print(f"触发策展的领域: {triggered}")
    for d in triggered:
        c.curate(d, date_str)
