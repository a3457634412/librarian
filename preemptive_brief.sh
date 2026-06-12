#!/usr/bin/env bash
# 资料管理员 — 主动简报
# 当某个标签连续活跃或用户反复搜索时，提前准备一份该领域的当前状态简报
# 用法: bash preemptive_brief.sh [--tag "#agent"] [--query "agent memory"]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/search_config.sh"
source "$SCRIPT_DIR/profile.sh" 2>/dev/null || true

BRIEF_DIR="$CURATED_DIR/preemptive"
mkdir -p "$BRIEF_DIR"

FORCE_TAG="${1:-}"
FORCE_QUERY="${2:-}"

# ── 判断是否需要生成简报 ──

need_brief_for_tag() {
    local tag="$1"
    local tag_name="${tag#\#}"

    # 检查是否已经有 7 天内的简报
    local existing
    existing=$(find "$BRIEF_DIR" -name "${tag_name}-简报*.md" -mtime -7 2>/dev/null | head -1)
    [ -n "$existing" ] && return 1

    # 检查连续活跃天数
    local consecutive=0
    for d in $(seq 0 6); do
        local cd
        cd=$(date -d "$d days ago" +%Y-%m-%d 2>/dev/null || echo "")
        [ -z "$cd" ] && continue
        local hit
        hit=$(grep -c "$tag" "$OBSIDIAN_DIR/${cd}.md" 2>/dev/null || echo "0")
        hit=$((hit + 0))
        if [ "$hit" -gt 0 ]; then
            consecutive=$((consecutive + 1))
        else
            break
        fi
    done

    [ "$consecutive" -ge "$CURATE_CONSEC_MIN_DAYS" ] && return 0

    # 检查近期搜索次数
    if [ -f "$PROFILE_FILE" ]; then
        local search_count
        search_count=$(jq -r --arg t "$tag_name" \
            '[.searches[] | select(.query | test($t;"i"))] | length' \
            "$PROFILE_FILE" 2>/dev/null || echo "0")
        [ "$search_count" -ge 2 ] && return 0
    fi

    return 1
}

# ── 生成简报 ──

generate_brief() {
    local tag="$1"
    local tag_name="${tag#\#}"
    local brief_file="$BRIEF_DIR/${tag_name}-简报-$(date +%Y-%m-%d).md"

    echo "  → 生成主动简报: $tag"

    # 收集该领域的知识基础（wiki + 踩坑 + 综述）
    local knowledge=""
    knowledge=$(find "$OBSIDIAN_VAULT/wiki" "$PITFALL_DIR" "$CURATED_DIR/reviews" \
        -name "*.md" -type f 2>/dev/null | while read -r f; do
        if grep -qi "${tag_name}" "$f" 2>/dev/null; then
            title=$(awk '/^# /{sub(/^# /,""); print; exit}' "$f" 2>/dev/null || basename "$f" .md)
            echo "- [[$(basename "$f" .md)|${title}]]"
        fi
    done | head -10)

    # 收集近期该标签文章
    local recent=""
    recent=$(for f in "$OBSIDIAN_DIR"/*.md; do
        [ -f "$f" ] || continue
        if grep -q "$tag" "$f" 2>/dev/null; then
            awk -v RS='[*][*][*]' -v t="$tag" '{
                if (index($0, t) == 0) next
                m = match($0, /\n## ([^\n]+)/)
                if (!m) next
                title = substr($0, m+4, RLENGTH-4)
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", title)
                match($0, /💡 ([^\n]+)/); ts = substr($0, RSTART+3, RLENGTH-3)
                if (ts == "") {
                    match($0, /🔮 ([^\n]+)/); ts = substr($0, RSTART+3, RLENGTH-3)
                }
                if (ts == "") ts = title
                printf "- **%s**: %s\n", title, ts
            }' "$f" 2>/dev/null
        fi
    done | tail -15)

    # Claude 生成简报
    local prompt
    prompt="你是知识管理员。请基于以下信息，为「${tag}」领域生成一份 300-500 字的当前状态简报。

## 已有知识基础
${knowledge:-（暂无相关笔记）}

## 近期动态
${recent:-（暂无近期动态）}

请按以下结构输出：
### 当前状态
一段话概括该领域在你知识库中的状态。

### 近期变化
2-3 条近期值得关注的动态或趋势。

### 建议关注
1-2 条具体的建议，比如需要更新的 wiki 条目、值得深入的方向、或可能的踩坑风险。

不要编造信息，基于提供的内容写。输出纯 Markdown。"

    printf '%s' "$prompt" | claude -p \
        --output-format text \
        --permission-mode bypassPermissions \
        --no-session-persistence \
        > "$brief_file" 2>/dev/null || {
        echo "  ⚠ Claude 调用失败，生成简化版简报"
        {
            echo "# ${tag} — 当前状态简报"
            echo ""
            echo "## 已有知识基础"
            echo "$knowledge"
            echo ""
            echo "## 近期动态"
            echo "$recent"
        } > "$brief_file"
    }

    echo "  ✅ 简报已生成: $brief_file"
    echo "$brief_file"
}

# ── 主逻辑 ──

if [ -n "$FORCE_TAG" ] && [[ "$FORCE_TAG" =~ ^--tag ]]; then
    generate_brief "$FORCE_QUERY"
    exit 0
fi

# 自动检测：遍历标签，看哪些需要简报
BRIEF_COUNT=0
for tag in "${TAG_ORDER[@]}"; do
    if need_brief_for_tag "$tag"; then
        generate_brief "$tag" && BRIEF_COUNT=$((BRIEF_COUNT + 1))
    fi
done

[ "$BRIEF_COUNT" -gt 0 ] && echo "BRIEFS:${BRIEF_COUNT}" || echo "无需主动简报"
