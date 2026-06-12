"""
关键词检索 + 排名
移植 search_engine.sh 的 match_and_score / rank / format 逻辑
"""
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from config import config


def match_and_score(query: str, vault_dir: Path, top_n: int = 20) -> list[dict]:
    """关键词匹配 + 打分"""
    kw_cfg = config["keyword"]
    keywords = query.lower().split()

    results = []
    for md in vault_dir.glob("**/*.md"):
        try:
            content = md.read_text(encoding="utf-8")
        except Exception:
            continue

        # 按 *** 分块
        blocks = content.split("***")
        for block in blocks:
            if not block.strip():
                continue
            block_lower = block.lower()

            score = 0.0
            for kw in keywords:
                # tag 匹配
                if f"`{kw}" in block_lower or f"#{kw}" in block_lower:
                    score += kw_cfg["weight_tag"]
                # title 匹配
                for line in block.split("\n"):
                    if line.strip().startswith("## ") and kw in line.lower():
                        score += kw_cfg["weight_title"]
                        break
                # 核心内容匹配 (💡)
                for line in block.split("\n"):
                    if line.strip().startswith("💡 ") and kw in line.lower():
                        score += kw_cfg["weight_core_content"]
                        break
                # 全文匹配
                score += block_lower.count(kw) * 0.01

            if score > 0:
                title = ""
                source = ""
                points = 0
                pub_date = ""
                for line in block.split("\n"):
                    if line.startswith("## "):
                        title = line[3:].strip()
                    elif line.startswith("date: "):
                        pub_date = line.split(":", 1)[1].strip()
                    elif "points" in line and "·" in line:
                        try:
                            points_str = line.split("·")[0].strip().replace("📊 ", "")
                            points = int(re.findall(r'\d+', points_str)[0])
                        except (ValueError, IndexError):
                            pass

                results.append({
                    "title": title, "score": score, "source": source,
                    "points": points, "date": pub_date, "block": block.strip()[:300],
                })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


def rank(results: list[dict]) -> list[dict]:
    """权威度 + 时效衰减"""
    ranking = config["ranking"]

    for r in results:
        authority = math.log10(r["points"] + 1) / ranking["authority_scale"]
        authority = min(authority, ranking["authority_max_boost"])

        days_old = 0
        if r.get("date"):
            try:
                d = datetime.strptime(r["date"], "%Y-%m-%d")
                days_old = (datetime.now() - d).days
            except ValueError:
                pass
        time_decay = max(ranking["time_decay_floor"], 0.3 + 0.7 * 0.7 ** (days_old / ranking["half_life_days"]))

        r["final_score"] = r["score"] * (1 + authority) * time_decay

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results[:ranking["max_results"]]


def format_results(results: list[dict]) -> str:
    """转为 Markdown 输出"""
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"**{i}. {r.get('title', '无标题')}** (score: {r.get('final_score', 0):.2f})")
        lines.append(f"{r.get('block', '')[:200]}")
        lines.append("")
    return "\n".join(lines)
