#!/usr/bin/env bash
# Reset the demo between judges: shop back to healthy, incidents cleared, Meko switch set.
# Lessons in Meko are kept. Usage: scripts/demo_reset.sh [on|off]   (default: off, the demo starts OFF)
#   FIXONCE_URL=http://<vm-ip>:8000 scripts/demo_reset.sh
set -euo pipefail

URL="${FIXONCE_URL:-http://localhost:8000}"
MEKO="${1:-off}"
case "$MEKO" in
  on) ENABLED=true ;;
  off) ENABLED=false ;;
  *) echo "usage: $0 [on|off]" >&2; exit 2 ;;
esac

post() { curl -fsS -m 15 -X POST -H "Content-Type: application/json" "$URL$1" ${2:+-d "$2"}; }

post /api/demo/reset >/dev/null
post /settings/meko "{\"enabled\": $ENABLED}" >/dev/null

STATUS="$(curl -fsS -m 10 "$URL/api/status")"
METRICS="$(curl -fsS -m 10 "$URL/metrics")"
INCIDENTS="$(curl -fsS -m 10 "$URL/incidents")"
echo "status:    $STATUS"
echo "metrics:   $METRICS"
echo "incidents: $INCIDENTS"

fail=0
grep -q "\"meko_enabled\":$ENABLED" <<<"$STATUS" || { echo "FAIL: Meko switch is not $MEKO"; fail=1; }
grep -q '"error_rate":0.003' <<<"$METRICS" || { echo "FAIL: shop is not healthy yet"; fail=1; }
[ "$INCIDENTS" = "[]" ] || { echo "FAIL: incidents not cleared"; fail=1; }
grep -q '"meko_backend":"fake-meko"' <<<"$STATUS" && echo "WARNING: running on the offline fake memory, not real Meko"
[ "$fail" = 0 ] && echo "OK: demo reset, Meko $MEKO, ready for the next judge"
exit "$fail"
