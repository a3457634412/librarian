"""
Librarian Agent — 主编排器

所有新文章（cron 抓取 / 手动投喂）统一走 process_incoming():
  1. LLM 打标签
  2. 写入 Obsidian
  3. 推送通知（可选）
  4. 标签统计 + 异常检测 + 关联笔记
  5. wiki 提炼
  6. 策展检测
  7. 冲突检测
  8. 归档
  9. 增量索引
  10. 知识图谱

用法:
  python agent.py                        # 完整 cron 运行（今天）
  python agent.py 2026-05-30             # 指定日期
  python agent.py --manual --url "..."   # 手动投喂 URL
  python agent.py --manual --text "标题" "内容"  # 手动投喂文本
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

from config import config

import fetch_sources
import tagger
import obsidian_writer
import notifier
import processor
import curator
import contradiction
import archiver
import indexer
import graph
import wiki_updater
from models import ArticleStore



def process_incoming(articles: list[dict], date_str: str, store: ArticleStore = None,
                     skip_notify: bool = False, tagged_file: str = None):
    """
    统一处理入口 — 所有新文章无论来源都走这里。

    articles: 原始文章列表（未打标签）
    date_str: 日期
    store: ArticleStore 实例（可选，不传则新建）
    skip_notify: 手动投喂时不推送
    tagged_file: 已有 tagged JSON 路径（cron 场景重用）
    """
    if store is None:
        store = ArticleStore()


    # ── 1. 打标签 ──
    print(f"  LLM 打标签 ({len(articles)} 篇)...")
    tagged = tagger.tag_articles(articles)
    if not tagged:
        print("  ⚠️ 标记失败，使用原始数据")
        tagged = articles

    tagged_for_store = []
    for a in tagged:
        aid = store._make_id(date_str, a.get("title", ""))
        if store.get(aid):
            a["id"] = aid
            tagged_for_store.append(a)
    if tagged_for_store:
        store.update_tags(tagged_for_store)

    # 保存 tagged JSON
    if tagged_file is None:
        tagged_file = str(Path(config["paths"]["data_dir"]) / f"{date_str}_tagged.json")
    json.dump(tagged, open(tagged_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # ── 2. 写入 Obsidian ──
    print(f"  写入 Obsidian...")
    if not skip_notify:
        obsidian_writer.write_daily_markdown(tagged_file, date_str)
    else:
        obsidian_writer.write_manual_markdown(tagged, date_str)

    # ── 3. 推送（仅 cron） ──
    if not skip_notify:
        try:
            n = notifier.Notifier()
            n.push_daily_summary(tagged_file, date_str)
        except Exception as e:
            print(f"  ⚠️ 推送失败: {e}")

    # ── 4. 处理 + 关联 ──
    try:
        proc = processor.Processor()
        proc.process(tagged_file, date_str)
    except Exception as e:
        print(f"  ⚠️ 处理失败: {e}")

    # ── 5. wiki 提炼 + 策展 ──
    _run_curation_pipeline(tagged, date_str, tagged_file)

    # ── 5.5. 全量维护 [[双向链接]]（不管有没有新文章，每天固定修）──
    try:
        wu = wiki_updater.WikiUpdater()
        wu.maintain_all_links()
    except Exception as e:
        print(f"  ⚠️ 自动连线失败: {e}")

    # ── 7. 冲突检测 ──
    try:
        cd = contradiction.ContradictionDetector()
        findings = cd.detect(tagged_file, date_str)
        if findings:
            print(f"  冲突检测: {len(findings)} 条")
    except Exception as e:
        print(f"  ⚠️ 冲突检测失败: {e}")

    # ── 8. 归档 ──
    try:
        archiver.archive(date_str)
    except Exception as e:
        print(f"  ⚠️ 归档失败: {e}")

    # ── 9. 增量索引 ──
    try:
        idx = indexer.Indexer()
        idx.build_index("--incremental")
    except Exception as e:
        print(f"  ⚠️ 索引失败: {e}")

    # ── 10. 知识图谱 ──
    try:
        kg = graph.KnowledgeGraph(config["graph"]["path"])
        for a in tagged[:3]:
            domain = a.get("domain", "其他")
            kg.add_triple("资料管理员", "收录", a["title"], confidence=5, evidence=f"{date_str} {domain}")
        kg.save()
    except Exception as e:
        print(f"  ⚠️ 知识图谱更新失败: {e}")

    return tagged


def _run_curation_pipeline(tagged: list[dict], date_str: str, tagged_file: str):
    """策展决策链 — feature flag 控制走新/旧逻辑"""
    use_multi = config.get("multi_agent_curation", {}).get("enabled", False)

    if not use_multi:
        # ── 旧逻辑: wiki_updater + curator ──
        try:
            wu = wiki_updater.WikiUpdater()
            updates = wu.update(tagged, date_str)
            if updates:
                print(f"  wiki 更新: {len(updates)} 个页面")
                for u in updates:
                    print(f"    {u['page']}")
        except Exception as e:
            print(f"  ⚠️ wiki 更新失败: {e}")

        try:
            cur = curator.Curator()
            triggered = cur.check_thresholds(date_str)
            if triggered:
                print(f"  触发策展: {triggered}")
                for tag in triggered:
                    try:
                        cur.curate(tag, date_str)
                    except Exception as e:
                        print(f"  ⚠️ 策展 {tag} 失败: {e}")
        except Exception as e:
            print(f"  ⚠️ 策展检查失败: {e}")
        return

    # ── 新逻辑: 多 Agent 策展 ──
    try:
        from multi_agent_curation.graph import run_curation_pipeline

        # 筛选 agent 领域的文章
        agent_articles = [a for a in tagged if a.get("domain") == "agent"]
        if not agent_articles:
            agent_articles = tagged

        run_curation_pipeline(
            agent_articles, date_str,
            dry_run=config.get("multi_agent_curation", {}).get("dry_run", False),
        )
    except ImportError:
        print("  ⚠️ multi_agent_curation 模块未安装，降级到旧逻辑")
        config.setdefault("multi_agent_curation", {})["enabled"] = False
        _run_curation_pipeline(tagged, date_str, tagged_file)
    except Exception as e:
        print(f"  ⚠️ 多 Agent 策展失败: {e}")
        import traceback
        traceback.print_exc()
        # 降级: 跑旧逻辑
        try:
            print("  → 降级到旧策展逻辑...")
            config.setdefault("multi_agent_curation", {})["enabled"] = False
            _run_curation_pipeline(tagged, date_str, tagged_file)
        except Exception as fb_e:
            print(f"  ⚠️ 降级也失败: {fb_e}")


def manual_ingest(url: str = None, text_title: str = None, text_content: str = None):
    """手动投喂入口"""
    from urllib.request import Request, urlopen

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    store = ArticleStore()

    if url:
        try:
            req = Request(url, headers={"User-Agent": "Librarian/1.0"})
            with urlopen(req, timeout=15) as resp:
                html = resp.read().decode(errors="ignore")
            m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
            title = m.group(1).strip() if m else url.split("/")[-1] or url
            body = re.sub(r'<[^>]+>', ' ', html)
            body = re.sub(r'\s+', ' ', body)
            article = {
                "title": title, "url": url, "source": "手动投喂",
                "points": 0, "published_at": now.isoformat(), "summary": body[:500],
            }
        except Exception as e:
            print(f"  ⚠️ 抓取失败: {e}")
            return
        print(f"  手动投喂: {article['title']}")
    elif text_title and text_content:
        article = {
            "title": text_title, "url": "", "source": "手动投喂",
            "points": 0, "published_at": now.isoformat(), "summary": text_content[:500],
        }
    else:
        print("用法: --manual --url <URL> 或 --manual --text <标题> <内容>")
        return

    store.ingest([article], date_str)
    process_incoming([article], date_str, store=store, skip_notify=True)
    print("  手动投喂完成")


def daily_run(date_str: str = None):
    """cron 每日完整管线"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    data_dir = Path(config["paths"]["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    store = ArticleStore()

    print(f"{'='*50}")
    print(f"  Librarian Agent — {date_str}")
    print(f"{'='*50}")

    # ── 补抓 + 抓取 ──
    print("\n[1/2] 抓取信源...")
    recovered = fetch_sources.retry_pending()
    if recovered:
        print(f"  补抓成功 {len(recovered)} 篇 → 入库")
        store.ingest(recovered, date_str)

    articles = fetch_sources.fetch_all()
    if not articles:
        print("  ⚠️ 所有信源返回空")
        return

    ingested_ids = store.ingest(articles, date_str)
    print(f"  ArticleStore: {len(ingested_ids)} 条新文章 (累计 {store.stats()['total']})")

    fetch_sources.save_raw(articles, date_str)

    # ── 统一处理 ──
    print(f"\n[2/2] 处理...")
    process_incoming(articles, date_str, store=store, skip_notify=False)

    print(f"\n{'='*50}")
    print(f"  完成 — {date_str}")
    s = store.stats()
    print(f"  ArticleStore: 共 {s['total']} 条 "
          f"(ingested:{s['by_state'].get('ingested', 0)} "
          f"tagged:{s['by_state'].get('tagged', 0)} "
          f"indexed:{s['by_state'].get('indexed', 0)} "
          f"archived:{s['by_state'].get('archived', 0)})")
    print(f"{'='*50}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--manual":
        if len(sys.argv) > 3 and sys.argv[2] == "--url":
            manual_ingest(url=sys.argv[3])
        elif len(sys.argv) > 4 and sys.argv[2] == "--text":
            manual_ingest(text_title=sys.argv[3], text_content=" ".join(sys.argv[4:]))
        else:
            print("用法: python agent.py --manual --url <URL>")
            print("      python agent.py --manual --text <标题> <内容>")
    else:
        date_str = sys.argv[1] if len(sys.argv) > 1 else None
        daily_run(date_str)
