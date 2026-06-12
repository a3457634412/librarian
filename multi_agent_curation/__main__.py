"""三人小组策展 — CLI 手动触发入口

用法:
    # 用今天的日期跑策展
    python -m multi_agent_curation

    # 指定日期
    python -m multi_agent_curation --date 2026-06-12

    # dry run (Wiki Agent 不写入)
    python -m multi_agent_curation --dry-run

    # 指定文章数量
    python -m multi_agent_curation --date 2026-06-12 --limit 10
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

LIBRARIAN_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(LIBRARIAN_DIR))


def load_recent_articles(date_str, limit=15):
    path = LIBRARIAN_DIR / "articles.json"
    if not path.exists():
        print(f"❌ 找不到 {path}")
        return []

    with open(path, "r", encoding="utf-8") as f:
        all_articles = json.load(f)

    target_date = date_str[:10]
    recent = [a for a in all_articles
              if a.get("date", "").startswith(target_date)
              or a.get("published_at", "").startswith(target_date)]

    if not recent:
        print(f"⚠️ {target_date} 没有文章，取最近 {limit} 篇 tagged 文章")
        tagged = [a for a in all_articles if a.get("status") == "tagged"]
        tagged.sort(key=lambda a: a.get("date", ""), reverse=True)
        recent = tagged[:limit]

    return recent[:limit]


def main():
    parser = argparse.ArgumentParser(description="三人小组策展 CLI")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="策展日期 (默认今天)")
    parser.add_argument("--limit", type=int, default=15,
                        help="最多处理文章数")
    parser.add_argument("--dry-run", action="store_true",
                        help="Wiki Agent 不实际写入")
    args = parser.parse_args()

    articles = load_recent_articles(args.date, args.limit)

    if not articles:
        print("❌ 没有可策展的文章")
        return

    print(f"📰 加载 {len(articles)} 篇文章 (日期: {args.date})")
    for i, a in enumerate(articles):
        title = a.get("title", "?")[:80]
        print(f"  [{i}] {title}")

    from multi_agent_curation.graph import run_curation_pipeline

    result = run_curation_pipeline(
        articles=articles,
        date_str=args.date,
        dry_run=args.dry_run,
    )

    print(f"\n📋 策展结果:")
    print(f"  信号: {len(result.get('signals', []))} 个")
    print(f"  决策: {len(result.get('curation_plan', []))} 条")
    print(f"  更新: {len(result.get('wiki_updates', []))} 项")
    if result.get("errors"):
        print(f"  ⚠️ 错误: {len(result['errors'])} 个")


if __name__ == "__main__":
    main()
