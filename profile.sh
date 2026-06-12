#!/usr/bin/env bash
# 资料管理员 — 搜索画像管理
# 用法: source profile.sh
set -euo pipefail

PROFILE_FILE="${PROFILE_FILE:-D:/Claude code/librarian/sessions/profile.json}"
PROFILE_RETENTION_DAYS=7
BLIND_SPOT_THRESHOLD=2

_profile_init() {
    [ -f "$PROFILE_FILE" ] && return 0
    mkdir -p "$(dirname "$PROFILE_FILE")"
    jq -n '{searches: [], tags: {}, blind_spots: [], updated: ""}' > "$PROFILE_FILE"
}

# 记录一次搜索
profile_record_search() {
    local query="$1" result_count="$2"
    _profile_init

    local today
    today=$(date +%Y-%m-%d)

    jq \
        --arg q "$query" \
        --arg rc "$result_count" \
        --arg ts "$(date -Iseconds)" \
        --arg d "$today" \
        '.searches += [{"query": $q, "result_count": ($rc | tonumber), "timestamp": $ts, "date": $d}] |
         .searches = (.searches | map(select(.date >= $d)))' \
        "$PROFILE_FILE" > "${PROFILE_FILE}.tmp" 2>/dev/null && mv "${PROFILE_FILE}.tmp" "$PROFILE_FILE"

    # 清理超过保留期的记录
    local cutoff
    cutoff=$(date -d "${PROFILE_RETENTION_DAYS} days ago" +%Y-%m-%d 2>/dev/null || echo "")
    [ -n "$cutoff" ] && jq --arg c "$cutoff" \
        '.searches = [.searches[] | select(.date >= $c)]' \
        "$PROFILE_FILE" > "${PROFILE_FILE}.tmp" 2>/dev/null && mv "${PROFILE_FILE}.tmp" "$PROFILE_FILE"
}

# 记录一次盲区（搜不到结果）
profile_record_blindspot() {
    local query="$1"
    _profile_init

    jq \
        --arg q "$query" \
        --arg ts "$(date -Iseconds)" \
        '.blind_spots += [{"query": $q, "timestamp": $ts, "count": 1}]' \
        "$PROFILE_FILE" > "${PROFILE_FILE}.tmp" 2>/dev/null && mv "${PROFILE_FILE}.tmp" "$PROFILE_FILE"

    # 合并同一查询的盲区记录
    jq '
        def merge_spots:
            reduce .[] as $s ({};
                .[$s.query] = {
                    query: $s.query,
                    count: ((.[$s.query].count // 0) + 1),
                    first_seen: (.[$s.query].first_seen // $s.timestamp),
                    last_seen: $s.timestamp
                }
            ) | to_entries | map(.value);
        .blind_spots = (merge_spots | map(select(.count >= '"${BLIND_SPOT_THRESHOLD}"')))
    ' "$PROFILE_FILE" > "${PROFILE_FILE}.tmp" 2>/dev/null && mv "${PROFILE_FILE}.tmp" "$PROFILE_FILE"
}

# 获取近期搜索的高频标签
profile_top_tags() {
    local top_n="${1:-5}"
    _profile_init
    jq -r '[.searches[].query] | join(" ") | scan("[a-zA-Z]+") | ascii_downcase | .[0:30]' \
        "$PROFILE_FILE" 2>/dev/null | sort | uniq -c | sort -rn | head -n "$top_n" | awk '{print $2}'
}

# 获取近期搜索的原始查询词
profile_recent_queries() {
    _profile_init
    jq -r '[.searches[] | .query] | unique | .[]' "$PROFILE_FILE" 2>/dev/null
}

# 获取已达到阈值的盲区查询列表
profile_blind_spots() {
    _profile_init
    jq -r '.blind_spots[]? | "\(.query) (\(.count)次搜索无结果)"' "$PROFILE_FILE" 2>/dev/null
}

# 获取个性化加权用的标签列表（空格分隔）
profile_boost_tags() {
    _profile_init
    jq -r '[.searches[] | .query] | join(" ") | ascii_downcase' "$PROFILE_FILE" 2>/dev/null | \
        grep -oE '\b(agent|rag|vllm|mcp|prompt|memory|embedding|retrieval|llm|model|deploy|quantize|tool|orchestrat)\w*' 2>/dev/null | \
        sort | uniq -c | sort -rn | head -8 | awk '{print $2}' | tr '\n' ' '
}

# 检测查询是否与近期搜索相关
profile_match_recent() {
    local text="$1"
    _profile_init
    local keywords
    keywords=$(profile_boost_tags)
    [ -z "$keywords" ] && return 1
    local text_lower
    text_lower=$(echo "$text" | tr '[:upper:]' '[:lower:]')
    for kw in $keywords; do
        if echo "$text_lower" | grep -q "$kw" 2>/dev/null; then
            return 0
        fi
    done
    return 1
}
