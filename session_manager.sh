#!/usr/bin/env bash
# 资料管理员 — 会话管理
# 用法：source session_manager.sh

SESSION_DIR="${SESSION_DIR:-D:/Claude code/librarian/sessions}"
SESSION_MAX_TURNS="${SESSION_MAX_TURNS:-10}"
SESSION_CONTEXT_TURNS="${SESSION_CONTEXT_TURNS:-3}"

mkdir -p "$SESSION_DIR"

session_init() {
    local id="$1"
    local file="$SESSION_DIR/${id}.json"
    jq -n \
        --arg id "$id" \
        --arg created "$(date -Iseconds)" \
        '{id: $id, created: $created, updated: $created, turns: []}' \
        > "$file"
    echo "$file"
}

session_add_turn() {
    local id="$1" query="$2" top_hits="$3"
    local file="$SESSION_DIR/${id}.json"
    [ ! -f "$file" ] && file=$(session_init "$id")

    jq \
        --arg q "$query" \
        --arg hits "$top_hits" \
        --arg ts "$(date -Iseconds)" \
        '.turns += [{"query": $q, "top_hits": $hits, "timestamp": $ts}] |
         .updated = $ts |
         .turns = (.turns | .[-'"${SESSION_MAX_TURNS}"':])' \
        "$file" > "${file}.tmp" 2>/dev/null && mv "${file}.tmp" "$file"
}

session_get_context() {
    local id="$1"
    local file="$SESSION_DIR/${id}.json"
    [ ! -f "$file" ] && return 0

    jq -r '.turns | .[-'"${SESSION_CONTEXT_TURNS}"':] | .[] |
        "查询: \(.query)\n关注: \(.top_hits)\n"' \
        "$file" 2>/dev/null
}

session_list() {
    for f in "$SESSION_DIR"/*.json; do
        [ ! -f "$f" ] && continue
        local id created turns
        id=$(jq -r '.id' "$f" 2>/dev/null)
        created=$(jq -r '.created[0:10]' "$f" 2>/dev/null)
        turns=$(jq -r '.turns | length' "$f" 2>/dev/null)
        echo "  $id | 创建: $created | $turns 轮"
    done
}

session_clear() {
    local id="$1"
    rm -f "$SESSION_DIR/${id}.json"
}
