#!/usr/bin/env bash
# Summarize ingest logs from journald (default) or a cron log file.
#
#   scripts/inspect_logs.sh [--since "24 hours ago"] [--file PATH] [--errors N]
#
# Reads the "poll status=..." lines that fda.ingest writes once per run.
set -euo pipefail

SINCE="24 hours ago"
FILE=""
SHOW_ERRORS=10

while [[ $# -gt 0 ]]; do
    case "$1" in
        --since)  SINCE="${2:?}"; shift ;;
        --file)   FILE="${2:?}"; shift ;;
        --errors) SHOW_ERRORS="${2:?}"; shift ;;
        -h|--help) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

if [[ -n "$FILE" ]]; then
    [[ -r "$FILE" ]] || { echo "cannot read $FILE" >&2; exit 1; }
    cp "$FILE" "$TMP"
    source_desc="$FILE"
else
    journalctl -u fda-ingest.service --since "$SINCE" -o short-iso --no-pager > "$TMP"
    source_desc="journald since '$SINCE'"
fi

echo "Source: $source_desc ($(wc -l < "$TMP") lines)"
echo

echo "Runs by status:"
grep -o 'poll status=[a-z_]*' "$TMP" | cut -d= -f2 | sort | uniq -c | sort -rn \
    | awk '{ printf "  %-16s %6d\n", $2, $1 }' || echo "  (no poll lines)"
echo

echo "Successful polls:"
{ grep 'poll status=ok' "$TMP" || true; } | awk '
    {
        for (i = 1; i <= NF; i++) {
            split($i, kv, "=")
            v[kv[1]] = kv[2]
        }
        n++
        states += v["states"]; flagged += v["flagged"]; rejected += v["rejected"]
        dur += v["duration_ms"]
        if (v["duration_ms"] > maxdur) maxdur = v["duration_ms"]
        if (v["states"] > peak) peak = v["states"]
        credits = v["credits_remaining"]
    }
    END {
        if (n == 0) { print "  none"; exit }
        printf "  count               %d\n", n
        printf "  avg aircraft/poll   %.1f (peak %d)\n", states / n, peak
        printf "  flagged records     %d\n", flagged
        printf "  rejected rows       %d\n", rejected
        printf "  avg / max duration  %.0f / %d ms\n", dur / n, maxdur
        printf "  credits remaining   %s (last poll)\n", credits
    }'
echo

echo "Retries (OpenSky 5xx / network): $(grep -c 'retrying OpenSky request' "$TMP" || true)"
echo "Rejected rows logged:            $(grep -c 'rejected row' "$TMP" || true)"
echo

echo "Last $SHOW_ERRORS ERROR lines:"
grep -E ' ERROR ' "$TMP" | tail -n "$SHOW_ERRORS" | sed 's/^/  /' || echo "  none"
