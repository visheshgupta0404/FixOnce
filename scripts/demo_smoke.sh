#!/usr/bin/env bash
# Runs the judged flow through the API: Meko ON must fix it first time, Meko OFF must not.
# On real Meko + Gemini each run uses about 8 Gemini requests (free tier: 20 per model per day) and leaves
# practice lessons in Meko: clear them afterwards with scripts/forget_practice_lessons.py.
# Usage: FIXONCE_URL=http://localhost:8000 scripts/demo_smoke.sh   (takes about a minute)
set -euo pipefail
URL="${FIXONCE_URL:-http://localhost:8000}"
post() { curl -fsS -m 45 -X POST -H "Content-Type: application/json" "$URL$1" ${2:+-d "$2"}; }
field() { grep -o "\"$1\":\"[^\"]*\"" | head -1 | cut -d\" -f4; }

run() {  # $1 = true|false; prints the final status and the actions tried
  post /api/demo/reset >/dev/null
  post /settings/meko "{\"enabled\": $1}" >/dev/null
  post /chaos/db_pool >/dev/null
  local id="" status="" i
  for i in $(seq 1 30); do  # the watcher opens the incident within a few seconds
    id="$(curl -fsS "$URL/incidents" | field id)"; [ -n "$id" ] && break; sleep 1
  done
  [ -n "$id" ] || { echo "no incident opened"; return 1; }
  for i in $(seq 1 120); do
    status="$(curl -fsS "$URL/incidents/$id" | field status)"
    case "$status" in
      resolved|escalated) break ;;
      waiting_human) post "/incidents/$id/decision" '{"choice": "apply"}' >/dev/null ;;
    esac
    sleep 1
  done
  echo "$status $(curl -fsS "$URL/incidents/$id" | grep -o '"attempts":\[[^]]*\]' | grep -o '"action":"[a-z_]*"' | cut -d'"' -f4 | tr '\n' ' ')"
}

off="$(run false)"; echo "Meko OFF: $off"
on="$(run true)";   echo "Meko ON:  $on"
post /api/demo/reset >/dev/null
# ON must fix it first time. OFF must not: handed to a senior, or (with a real LLM guessing) fixed only after other tries.
[[ "$on" == "resolved pause_batch_job " && "$off" != "resolved pause_batch_job " && ( "$off" == escalated* || "$off" == resolved* ) ]] \
  && echo "PASS" || { echo "FAIL"; exit 1; }
