"""多 Agent 策展 — 日志记录

每个 Agent 的输入/输出按日期存为独立 JSON 文件。
每天跑完生成一份人类可读的 decisions_summary.md。
"""

import json
from datetime import datetime
from pathlib import Path

LOG_BASE = Path("D:/Claude code/librarian/logs/multi_agent_curation")


def _ensure_dir(date_str: str) -> Path:
    d = LOG_BASE / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_agent(date_str: str, agent_name: str, input_data: dict, output_data: dict):
    """记录单个 Agent 的输入输出"""
    d = _ensure_dir(date_str)
    record = {
        "agent": agent_name,
        "timestamp": datetime.now().isoformat(),
        "input": input_data,
        "output": output_data,
    }
    f = d / f"{agent_name}.json"
    # append 模式 — 同一天多次执行不覆盖
    records = []
    if f.exists():
        try:
            records = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            records = []
    records.append(record)
    f.write_text(json.dumps(records, ensure_ascii=False, indent=2))


def log_error(date_str: str, agent_name: str, error: str):
    """记录 Agent 失败"""
    d = _ensure_dir(date_str)
    record = {
        "agent": agent_name,
        "timestamp": datetime.now().isoformat(),
        "error": error,
    }
    f = d / "errors.json"
    records = []
    if f.exists():
        try:
            records = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            records = []
    records.append(record)
    f.write_text(json.dumps(records, ensure_ascii=False, indent=2))


def save_summary(date_str: str, state_dict: dict):
    """生成人类可读的策展决策摘要"""
    d = _ensure_dir(date_str)
    lines = [
        f"# 多 Agent 策展决策摘要",
        f"",
        f"**日期**: {date_str}",
        f"**文章总数**: {state_dict.get('article_count', 0)}",
        f"**生成时间**: {datetime.now().strftime('%H:%M:%S')}",
        f"",
        f"---",
        f"",
        f"## Signal Agent — 检测到的信号",
        f"",
    ]

    for i, s in enumerate(state_dict.get("signals", [])):
        lines.append(f"### 信号 {i+1}: {s.get('signal', '')}")
        lines.append(f"- **类型**: {s.get('type', '')}")
        lines.append(f"- **置信度**: {s.get('confidence', '')}")
        lines.append(f"- **依据**: {', '.join(s.get('evidence', []))}")
        if s.get("suggested_action"):
            lines.append(f"- **建议动作**: {s['suggested_action']}")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## Curation Agent — 策展决策",
        "",
    ])

    for i, d_item in enumerate(state_dict.get("curation_plan", [])):
        lines.append(f"### 决策 {i+1}: {d_item.get('signal', '')}")
        lines.append(f"- **决策**: {d_item.get('decision', '')}")
        lines.append(f"- **理由**: {d_item.get('rationale', '')}")
        if d_item.get("target_page"):
            lines.append(f"- **目标页面**: {d_item['target_page']}")
        if d_item.get("merge_target"):
            lines.append(f"- **合并到**: {d_item['merge_target']}")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## Wiki Agent — 执行结果",
        "",
    ])

    for i, u in enumerate(state_dict.get("wiki_updates", [])):
        lines.append(f"### 更新 {i+1}")
        lines.append(f"- **页面**: {u.get('page', '')}")
        lines.append(f"- **动作**: {u.get('action', '')}")
        lines.append(f"- **状态**: {u.get('status', '')}")
        if u.get("reason"):
            lines.append(f"- **理由**: {u['reason']}")
        lines.append("")

    if state_dict.get("errors"):
        lines.extend([
            "---",
            "",
            "## ⚠️ 错误",
            "",
        ])
        for e in state_dict["errors"]:
            lines.append(f"- {e}")

    summary_path = d / "decisions_summary.md"
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    return str(summary_path)
