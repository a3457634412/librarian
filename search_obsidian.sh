#!/usr/bin/env bash
# 资料管理员 — 入口（V3: 支持多轮对话）
# 用法:
#   bash search_obsidian.sh "查询词"
#   bash search_obsidian.sh "查询词" --session <id>     ← 开启会话
#   bash search_obsidian.sh --list-sessions             ← 列会话
#   bash search_obsidian.sh --clear-session <id>        ← 删会话
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/search_config.sh"
source "$SCRIPT_DIR/search_engine.sh"
source "$SCRIPT_DIR/session_manager.sh"
source "$SCRIPT_DIR/profile.sh"

# ── 特殊命令 ──

if [ "${1:-}" = "--list-sessions" ]; then
    echo "活跃会话:"
    session_list
    exit 0
fi

if [ "${1:-}" = "--clear-session" ]; then
    session_clear "${2:-}"
    echo "会话已清除: ${2:-}"
    exit 0
fi

# 解析参数

query="${1:-}"
session_id=""
force_new=false
filter_relevance=""
filter_explicit=false

shift 2>/dev/null || true
while [ $# -gt 0 ]; do
    case "$1" in
        --session)
            session_id="${2:-}"
            shift 2
            ;;
        --new-session)
            force_new=true
            shift
            ;;
        --no-filter)
            filter_relevance=""
            filter_explicit=true
            shift
            ;;
        --filter)
            filter_val="${2:-}"
            if [[ "$filter_val" =~ relevance=(.+) ]]; then
                filter_relevance="${BASH_REMATCH[1]}"
                filter_relevance="${filter_relevance%\'}"
                filter_relevance="${filter_relevance#\'}"
                filter_relevance="${filter_relevance%\"}"
                filter_relevance="${filter_relevance#\"}"
            fi
            filter_explicit=true
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# 默认过滤
if [ "$filter_explicit" = false ] && [ -z "$filter_relevance" ]; then
    filter_relevance="${DEFAULT_FILTER_RELEVANCE:-}"
fi

if [ -z "$query" ]; then
    echo "用法: bash $0 \"查询词\" [--session <id>] [--no-filter] [--new-session]"
    echo "      bash $0 --list-sessions"
    echo "      bash $0 --clear-session <id>"
    exit 1
fi

# ── 日志 ──
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"
exec 2>>"$LOG_FILE"

{
    echo "=============================="
    echo "查询时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "查询词:   $query"
    echo "会话:     ${session_id:-无}"
    echo "过滤:     ${filter_relevance:-无}"
} >> "$LOG_FILE"

# ── 会话上下文（V3） ──
CONTEXT=""
if [ -n "$session_id" ]; then
    if $force_new || [ ! -f "$SESSION_DIR/${session_id}.json" ]; then
        session_init "$session_id" > /dev/null
        echo "  📝 新会话: $session_id" >> "$LOG_FILE"
    fi
    CONTEXT=$(session_get_context "$session_id")
    if [ -n "$CONTEXT" ]; then
        # 把上下文拼入查询词（增强语义检索的意图理解）
        query="${query}
[对话历史]
${CONTEXT}"
        echo "  📋 带上下文（最近 ${SESSION_CONTEXT_TURNS} 轮）" >> "$LOG_FILE"
    fi
fi

# ── 清理超过 1 天的残留临时文件 ──
find "$LOG_DIR" -maxdepth 1 \( -name ".kw_*.tsv" -o -name ".sem_*.tsv" \) -mtime +0 -delete 2>/dev/null || true

# ── D1: 主动简报检查 ──
BRIEF_PREPEND=""
BRIEF_DIR="$CURATED_DIR/preemptive"
if [ -d "$BRIEF_DIR" ]; then
    QUERY_LOWER=$(echo "$query" | tr '[:upper:]' '[:lower:]')
    for bf in "$BRIEF_DIR"/*-简报-*.md; do
        [ -f "$bf" ] || continue
        bf_name=$(basename "$bf" .md)
        bf_tag=$(echo "$bf_name" | sed 's/-简报-.*//')
        if echo "$QUERY_LOWER" | grep -qi "$bf_tag" 2>/dev/null; then
            BRIEF_PREPEND=$(head -80 "$bf" 2>/dev/null)
            BRIEF_PREPEND="${BRIEF_PREPEND}

---
📋 以上为主动简报（基于近期活跃自动生成）
"
            echo "  📋 命中主动简报: $bf_name" >> "$LOG_FILE"
            break
        fi
    done
fi

# ── V2 混合检索 ──
KW_TMP="$LOG_DIR/.kw_$$.tsv"
SEM_TMP="$LOG_DIR/.sem_$$.tsv"

match_and_score "$query" "$filter_relevance" > "$KW_TMP" 2>/dev/null || true
match_semantic "$query" > "$SEM_TMP" 2>/dev/null || true

MERGE_SCRIPT="D:/Claude code/librarian/hybrid_merge.py"
if [ -f "$MERGE_SCRIPT" ] && [ -s "$SEM_TMP" ]; then
    RESULT=$(python "$MERGE_SCRIPT" "$KW_TMP" "$SEM_TMP" "$HYBRID_KEYWORD_WEIGHT" "$HYBRID_SEMANTIC_WEIGHT" 2>/dev/null | rank | format)
    MODE="hybrid"
else
    RESULT=$(cat "$KW_TMP" | rank | format)
    MODE="keyword"
fi

# ── 知识边界感知 ──
BOUNDARY_WARN=""
if [ -s "$SEM_TMP" ]; then
    MAX_SEM=$(awk -F'|' 'BEGIN{max=0} {if($2+0>max)max=$2+0} END{print max}' "$SEM_TMP")
    if [ -n "$MAX_SEM" ] && [ "$(echo "$MAX_SEM < $BOUNDARY_THRESHOLD" | bc -l 2>/dev/null || echo 0)" = "1" ]; then
        BOUNDARY_WARN="\n\n⚠ 知识库内没有直接相关的内容（最高语义匹配度 $(printf '%.0f' "$(echo "$MAX_SEM * 100" | bc -l)")%）。建议从以下渠道查找：\n- Arxiv / Google Scholar 搜索相关关键词\n- 引用文献的原始论文\n- 在 curator 中为该领域标记策展需求"
        echo "  ⚠ 语义最高分 ${MAX_SEM} < ${BOUNDARY_THRESHOLD}，附加边界提醒" >> "$LOG_FILE"
    fi
fi

rm -f "$KW_TMP" "$SEM_TMP"

if [ -z "${RESULT:-}" ]; then
    echo "未找到匹配内容"
    echo "结果: 0 条 (${MODE})" >> "$LOG_FILE"
    exit 0
fi

COUNT=$(echo "$RESULT" | grep -c "^---$" || true)

{
    echo "命中:     $COUNT 条"
    echo "模式:     $MODE"
    echo "=============================="
} >> "$LOG_FILE"

# ── 搜索画像 ──
profile_record_search "$query" "${COUNT:-0}"
if [ "${COUNT:-0}" -eq 0 ] || [ -n "$BOUNDARY_WARN" ]; then
    profile_record_blindspot "$query"
fi

# ── 保存会话（V3） ──
if [ -n "$session_id" ]; then
    # 提取 top 结果标题（取前 3 个 ### 标题）
    TOP_HITS=$(echo "$RESULT" | grep "^## " | head -3 | sed 's/^## //' | tr '\n' '、' | sed 's/、$//')
    session_add_turn "$session_id" "${1:-$query}" "${TOP_HITS:-无}"
fi

if [ -n "$BRIEF_PREPEND" ]; then
    echo -e "$BRIEF_PREPEND"
fi
echo "$RESULT"
if [ -n "$BOUNDARY_WARN" ]; then
    echo -e "$BOUNDARY_WARN"
fi
