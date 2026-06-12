"""
三人小组每日评测 — 独立于管线运行

读取当天日志 → LLM 逐项评分 → 写 review.md + 更新 review_tracker.json

用法:
  python reviewer.py                     # 评测今天
  python reviewer.py 2026-06-03          # 评测指定日期
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import os
from openai import OpenAI

from multi_agent_curation.llm import parse_json
from multi_agent_curation.tools import read_wiki_page
from config import QWEN_API_KEY, QWEN_BASE_URL

_qwen_client = OpenAI(base_url=QWEN_BASE_URL, api_key=QWEN_API_KEY)


def _call_qwen(prompt: str, max_tokens: int = 3000, temperature: float = 0.2) -> str:
    resp = _qwen_client.chat.completions.create(
        model="qwen-plus",
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or ""

LOG_DIR = Path("D:/Claude code/librarian/logs/multi_agent_curation")
TRACKER_FILE = LOG_DIR / "review_tracker.json"
WIKI_ROOT = Path("D:/obsidian/1/wiki")


REVIEW_PROMPT = """你是苛刻的 Agent 系统评测员。评估一个三人小组今天的策展质量。

重要: 你的打分直接影响这个系统的迭代方向。过于宽松 = 系统永远不知道自己有多差。
不能给满分。每项评分应在 2-4 之间，只有真正例外的情况才给 5。
如果你发现不了任何问题，说明你看得不够仔细——重新审视。

## 今天的输入

### 原始文章
__ARTICLES_SUMMARY__

### Signal Agent 输出
__SIGNALS__

### Curation Agent 输出
__CURATION_PLAN__

### Wiki Agent 输出
__WIKI_UPDATES__

### Wiki 页面修改前后对比
__WIKI_DIFFS__

## 评测任务

对每个 Agent 逐项打分（1-5 分）:

### Signal Agent（满分 15）
- **recall**: 有没有值得关注的信号被漏掉？（1=漏很多, 3=基本覆盖, 5=全抓到）
- **precision**: 信号是否都有实质价值？（1=大部分是噪音, 3=有干货有水分, 5=每个都有干货）
- **clarity**: 信号描述清晰、有具体依据？（1=笼统, 3=基本清楚, 5=精确）

### Curation Agent（满分 20）
- **decision_quality**: curate/merge/skip 判断对不对？（1=多处错判, 3=基本合理, 5=全对）
- **target_accuracy**: 目标 wiki 页面选对了吗？（1=指错了, 3=基本对, 5=全准）
- **conservatism**: 是否优先更新已有页面？（1=乱建新页面, 3=基本克制, 5=完美克制）
- **reasoning**: 决策理由是否充分？（1=敷衍, 3=有理由, 5=有理有据有洞察）

### Wiki Agent（满分 20）
- **content_quality**: 写的有没有知识增量？（1=水文, 3=有信息, 5=有洞察）
- **structure**: 插入位置/目录结构是否正确？（1=乱塞, 3=基本对, 5=精准）
- **approval_accuracy**: 批准/驳回判断对不对？（1=该批的驳了/该驳的批了, 3=基本对, 5=全对）
- **no_degradation**: 有没有把好内容改差？（1=明显退化, 3=没退化, 5=反而提升了）

### 全局（满分 10）
- **signal_to_curation_flow**: 两级之间有没有断裂？（Signal high→Curation skip 或 Signal low→Curation curate）（1=严重断裂, 3=基本顺畅, 5=完美）
- **overall_value**: 今天的策展对用户成为资深 Agent 工程师有没有帮助？（1=浪费时间, 3=有点用, 5=非常有价值）

## 输出 JSON

```json
{
  "date": "__DATE__",
  "overall_score": 0,
  "signal": {"recall": 0, "precision": 0, "clarity": 0, "total": 0, "note": ""},
  "curation": {"decision_quality": 0, "target_accuracy": 0, "conservatism": 0, "reasoning": 0, "total": 0, "note": ""},
  "wiki": {"content_quality": 0, "structure": 0, "approval_accuracy": 0, "no_degradation": 0, "total": 0, "note": ""},
  "global": {"signal_to_curation_flow": 0, "overall_value": 0, "total": 0, "note": ""},
  "flags": ["需人工复查: xxx"],
  "suggestions": ["xxx"]
}
```

规则：
- 必须指出至少 1 条具体的改进建议
- 如果有 4-5 分，必须在 note 里给出明确的理由
- flags 标注必须人工确认的项
- 只输出 JSON"""


def _build_articles_summary(agent_log: dict) -> str:
    """从 Signal Agent 日志提取文章摘要"""
    articles_info = agent_log.get("input", {}).get("articles_text_len", 0)
    signals = agent_log.get("output", {}).get("signals", [])
    article_count = agent_log.get("input", {}).get("article_count", 0)
    lines = [f"共 {article_count} 篇文章"]
    # 从信号中反推涉及的文章
    for s in signals:
        evidence = s.get("evidence", [])
        if evidence:
            lines.append(f"- 信号相关: {', '.join(evidence[:5])}")
    return "\n".join(lines)


def _build_wiki_diffs(date_str: str) -> str:
    """构建 wiki 修改前后对比, 用 git diff"""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "-C", str(WIKI_ROOT), "diff", "--", "wiki/agent/"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout[:4000]
    except Exception:
        pass

    # git 不可用 → fallback: 列出今天修改的文件
    lines = []
    wiki_agent_file = LOG_DIR / date_str / "wiki_agent.json"
    if wiki_agent_file.exists():
        records = json.loads(wiki_agent_file.read_text(encoding="utf-8"))
        for r in records:
            for u in r.get("output", {}).get("updates", []):
                page = u.get("page", "")
                if page and u.get("status") == "written":
                    content = read_wiki_page(page)
                    if content:
                        lines.append(f"### {page}\n\n{content[:1500]}\n")
    return "\n".join(lines)


def review_date(date_str: str = None) -> dict:
    """评测指定日期的三人小组表现"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    log_date_dir = LOG_DIR / date_str
    if not log_date_dir.exists():
        print(f"⚠️ 日志目录不存在: {log_date_dir}")
        return {}

    print(f"三人小组评测 — {date_str}")

    # ── 读取日志 ──
    signal_log = _read_agent_log(log_date_dir, "signal_agent")
    curation_log = _read_agent_log(log_date_dir, "curation_agent")
    wiki_log = _read_agent_log(log_date_dir, "wiki_agent")

    if not signal_log:
        print("  ⚠️ 无 Signal Agent 日志，跳过评测")
        return {}

    # ── 构建评测上下文 ──
    articles_summary = _build_articles_summary(signal_log[-1])
    signals = json.dumps(
        signal_log[-1].get("output", {}).get("signals", []),
        ensure_ascii=False, indent=2,
    )
    curation_plan = json.dumps(
        curation_log[-1].get("output", {}).get("plan", []) if curation_log else [],
        ensure_ascii=False, indent=2,
    )
    wiki_updates = json.dumps(
        wiki_log[-1].get("output", {}).get("updates", []) if wiki_log else [],
        ensure_ascii=False, indent=2,
    )
    wiki_diffs = _build_wiki_diffs(date_str)

    prompt = REVIEW_PROMPT.replace("__DATE__", date_str)\
        .replace("__ARTICLES_SUMMARY__", articles_summary)\
        .replace("__SIGNALS__", signals)\
        .replace("__CURATION_PLAN__", curation_plan)\
        .replace("__WIKI_UPDATES__", wiki_updates)\
        .replace("__WIKI_DIFFS__", wiki_diffs)

    # ── 调 LLM 评测 ──
    print(f"  评测中...")
    try:
        raw = _call_qwen(prompt, max_tokens=3000, temperature=0.2)
        review = parse_json(raw)
    except Exception as e:
        print(f"  ⚠️ LLM 评测失败: {e}")
        review = {"error": str(e), "date": date_str}

    if not review or not isinstance(review, dict):
        print(f"  ⚠️ 解析失败")
        review = {"error": "parse failed", "date": date_str, "raw": raw[:500]}

    # ── 计算总分 ──
    if "signal" in review:
        s = review["signal"]
        s["total"] = s.get("recall", 0) + s.get("precision", 0) + s.get("clarity", 0)
    if "curation" in review:
        c = review["curation"]
        c["total"] = c.get("decision_quality", 0) + c.get("target_accuracy", 0) + \
                     c.get("conservatism", 0) + c.get("reasoning", 0)
    if "wiki" in review:
        w = review["wiki"]
        w["total"] = w.get("content_quality", 0) + w.get("structure", 0) + \
                     w.get("approval_accuracy", 0) + w.get("no_degradation", 0)
    if "global" in review:
        g = review["global"]
        g["total"] = g.get("signal_to_curation_flow", 0) + g.get("overall_value", 0)

    total_possible = 15 + 20 + 20 + 10  # 65
    achieved = (
        review.get("signal", {}).get("total", 0) +
        review.get("curation", {}).get("total", 0) +
        review.get("wiki", {}).get("total", 0) +
        review.get("global", {}).get("total", 0)
    )
    review["overall_score"] = round(achieved / total_possible * 100)

    # ── 写入 review.md ──
    _write_review_md(log_date_dir, review, date_str)

    # ── 更新 tracker ──
    _update_tracker(review)

    # ── 打印摘要 ──
    _print_summary(review)

    return review


def _read_agent_log(log_date_dir: Path, agent_name: str) -> list | None:
    f = log_date_dir / f"{agent_name}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_review_md(log_date_dir: Path, review: dict, date_str: str):
    lines = [
        f"# 三人小组评测 — {date_str}",
        f"",
        f"**总分**: {review.get('overall_score', '?')}/100",
        f"",
        "---",
        "",
        "## Signal Agent",
        f"- recall: {_stars(review, 'signal', 'recall')}",
        f"- precision: {_stars(review, 'signal', 'precision')}",
        f"- clarity: {_stars(review, 'signal', 'clarity')}",
        f"- **小计**: {review.get('signal', {}).get('total', 0)}/15",
        f"> {review.get('signal', {}).get('note', '')}",
        "",
        "## Curation Agent",
        f"- decision_quality: {_stars(review, 'curation', 'decision_quality')}",
        f"- target_accuracy: {_stars(review, 'curation', 'target_accuracy')}",
        f"- conservatism: {_stars(review, 'curation', 'conservatism')}",
        f"- reasoning: {_stars(review, 'curation', 'reasoning')}",
        f"- **小计**: {review.get('curation', {}).get('total', 0)}/20",
        f"> {review.get('curation', {}).get('note', '')}",
        "",
        "## Wiki Agent",
        f"- content_quality: {_stars(review, 'wiki', 'content_quality')}",
        f"- structure: {_stars(review, 'wiki', 'structure')}",
        f"- approval_accuracy: {_stars(review, 'wiki', 'approval_accuracy')}",
        f"- no_degradation: {_stars(review, 'wiki', 'no_degradation')}",
        f"- **小计**: {review.get('wiki', {}).get('total', 0)}/20",
        f"> {review.get('wiki', {}).get('note', '')}",
        "",
        "## 全局",
        f"- signal_to_curation_flow: {_stars(review, 'global', 'signal_to_curation_flow')}",
        f"- overall_value: {_stars(review, 'global', 'overall_value')}",
        f"- **小计**: {review.get('global', {}).get('total', 0)}/10",
        f"> {review.get('global', {}).get('note', '')}",
        "",
    ]

    flags = review.get("flags", [])
    if flags:
        lines.append("## ⚠️ 需人工确认")
        for f in flags:
            lines.append(f"- [ ] {f}")
        lines.append("")

    suggestions = review.get("suggestions", [])
    if suggestions:
        lines.append("## 💡 优化建议")
        for s in suggestions:
            lines.append(f"- {s}")
        lines.append("")

    md_path = log_date_dir / "review.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  评测报告: {md_path}")


def _stars(review: dict, section: str, key: str) -> str:
    score = review.get(section, {}).get(key, 0)
    filled = "★" * score
    empty = "☆" * (5 - score)
    return f"{filled}{empty} ({score}/5)"


def _update_tracker(review: dict):
    """累计评测数据到 review_tracker.json"""
    tracker = {"daily": [], "trends": {}}
    if TRACKER_FILE.exists():
        try:
            tracker = json.loads(TRACKER_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 防止同一天重复插入
    date_str = review.get("date", "")
    tracker["daily"] = [d for d in tracker.get("daily", []) if d.get("date") != date_str]

    entry = {
        "date": date_str,
        "overall_score": review.get("overall_score"),
        "signal_total": review.get("signal", {}).get("total"),
        "curation_total": review.get("curation", {}).get("total"),
        "wiki_total": review.get("wiki", {}).get("total"),
        "global_total": review.get("global", {}).get("total"),
        "flags_count": len(review.get("flags", [])),
        "suggestions_count": len(review.get("suggestions", [])),
    }
    tracker["daily"].append(entry)

    # 计算趋势
    daily = tracker["daily"]
    if len(daily) >= 2:
        recent = daily[-7:]  # 最近 7 天
        tracker["trends"] = {
            "avg_overall": round(sum(d["overall_score"] for d in recent) / len(recent)),
            "avg_signal": round(sum(d["signal_total"] for d in recent if d["signal_total"]) / len(recent), 1),
            "avg_curation": round(sum(d["curation_total"] for d in recent if d["curation_total"]) / len(recent), 1),
            "avg_wiki": round(sum(d["wiki_total"] for d in recent if d["wiki_total"]) / len(recent), 1),
            "days_tracked": len(daily),
            "score_delta": daily[-1]["overall_score"] - daily[-2]["overall_score"] if len(daily) >= 2 else 0,
        }

    TRACKER_FILE.write_text(json.dumps(tracker, ensure_ascii=False, indent=2))


def _print_summary(review: dict):
    print(f"\n  {'='*40}")
    print(f"  总分: {review.get('overall_score', '?')}/100")
    print(f"  Signal:  {review.get('signal', {}).get('total', 0)}/15")
    print(f"  Curation: {review.get('curation', {}).get('total', 0)}/20")
    print(f"  Wiki:    {review.get('wiki', {}).get('total', 0)}/20")
    print(f"  全局:    {review.get('global', {}).get('total', 0)}/10")
    flags = review.get("flags", [])
    if flags:
        print(f"  ⚠️ {len(flags)} 条需人工确认")
    print(f"  {'='*40}")


if __name__ == "__main__":
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    review_date(date_str)
