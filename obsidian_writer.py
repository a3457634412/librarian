"""
Obsidian Markdown 写入 — 按领域分目录

cron 文章 → raw/{domain}/每日/YYYY-MM-DD.md
手动投喂 → raw/{domain}/手动/YYYY-MM-DD-HH-MM-title.md
"""
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from config import config


def write_daily_markdown(tagged_file: str, date_str: str = None):
    """cron 批量写入 — 按领域分目录，每个领域一个文件"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    raw_base = Path(config["paths"]["obsidian_raw"])

    with open(tagged_file, "r", encoding="utf-8") as f:
        articles = json.load(f)

    total = len(articles)

    # 按领域分组
    by_domain = defaultdict(list)
    for a in articles:
        domain = a.get("domain", "其他")
        by_domain[domain].append(a)

    for domain, domain_articles in by_domain.items():
        domain_dir = raw_base / domain / "每日"
        domain_dir.mkdir(parents=True, exist_ok=True)
        output_file = domain_dir / f"{date_str}.md"

        relevant = [a for a in domain_articles if a.get("relevance_to_me") and a["relevance_to_me"] != "不直接相关"]

        lines = [
            "---",
            f"date: {date_str}",
            f"domain: {domain}",
            f"source: Simon Willison + GitHub Trending + Hacker News",
            f"total: {len(domain_articles)}",
            f"relevant: {len(relevant)}",
            "---",
            "",
            f"# {date_str} {domain} 动态",
            "",
            f"> 共 {len(domain_articles)} 条，其中 {len(relevant)} 条与你相关",
            "",
        ]

        for a in domain_articles:
            core = a.get("core_content", "")
            values = a.get("value_judgment", "")
            relevance = a.get("relevance_to_me", "")
            url = a.get("url", "")
            points = a.get("points", 0)
            source = a.get("source", "")

            entry = [
                "***",
                f"`{domain}` · {source}",
                "",
                f"## {a.get('title', '')}",
                "",
            ]
            if core:
                entry.append(f"💡 {core}")
                entry.append("")
            if values:
                entry.append(f"🔮 {values}")
                entry.append("")
            if relevance and relevance != "不直接相关":
                entry.append(f"🎯 {relevance}")
                entry.append("")
            entry.append(f"🔗 {url}")
            entry.append(f"📊 {points} points")
            entry.append("")

            lines.extend(entry)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        print(f"  已写入: raw/{domain}/每日/{date_str}.md ({len(domain_articles)} 篇)")


def write_manual_markdown(tagged: list[dict], date_str: str):
    """手动投喂 — 每篇独立 .md 到 raw/{domain}/手动/"""
    raw_base = Path(config["paths"]["obsidian_raw"])
    now = datetime.now()

    for a in tagged:
        domain = a.get("domain", "其他")
        domain_dir = raw_base / domain / "手动"
        domain_dir.mkdir(parents=True, exist_ok=True)

        safe_title = re.sub(r'[\\/:*?"<>|]', '-', a.get('title', 'untitled'))[:60]
        filename = f"{now.strftime('%Y-%m-%d-%H-%M')}-{safe_title}.md"
        filepath = domain_dir / filename

        content = f"""---
date: {date_str}
domain: {domain}
source: 手动投喂
url: {a.get('url', '')}
---

# {a['title']}

💡 {a.get('core_content', '')}

🔮 {a.get('value_judgment', '')}

{f'🎯 {a.get("relevance_to_me", "")}' if a.get('relevance_to_me') else ''}
"""
        filepath.write_text(content, encoding="utf-8")
        print(f"  已写入: raw/{domain}/手动/{filename}")


if __name__ == "__main__":
    import sys
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    file = f"D:/Claude code/获取信息/data/{date_str or datetime.now().strftime('%Y-%m-%d')}_tagged.json"
    write_daily_markdown(file, date_str)
