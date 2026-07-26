#!/usr/bin/env bash
#
# Rebuild, sanity-check, and ship.
#
#   ./deploy.sh            rebuild + deploy to production
#   ./deploy.sh --preview  rebuild + deploy to a preview URL
#   ./deploy.sh --local    rebuild only, serve on :8899
#
# The page is one self-contained file: nothing builds on Vercel, so a
# broken local build would deploy silently. The checks below are the
# reason this is a script and not two commands.

set -euo pipefail
cd "$(dirname "$0")"

SEED="${SEED:-7}"
MODE="${1:-}"
say() { printf '\033[36m▸\033[0m %s\n' "$*"; }
die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

say "regenerating scene data (seed $SEED)"
python3 viz/scene3d.py --seed "$SEED" >/tmp/at-scene.log 2>&1 \
  || { cat /tmp/at-scene.log; die "scene3d.py failed"; }
grep -E 'recall:|population full access' /tmp/at-scene.log | sed 's/^/    /'

say "bundling"
python3 viz/build3d.py | sed 's/^/    /'

# --- sanity checks -------------------------------------------------------
# Each of these has actually gone wrong at least once.
PAGE=out/index.html
[ -f "$PAGE" ] || die "no $PAGE"
BYTES=$(wc -c < "$PAGE" | tr -d ' ')
[ "$BYTES" -gt 500000 ] || die "page is only $BYTES bytes — bundle looks truncated"
grep -q 'const THREE=' "$PAGE" || die "three.js namespace missing from bundle"
grep -q 'scene-data' "$PAGE"   || die "scene data missing from bundle"
grep -q '<title>'    "$PAGE"   || die "no <title> — tab and share card would be blank"
RECALL=$(python3 -c "import json;d=json.load(open('out/scene.json'));r=d['recall'];print(f\"{r['detected']}/{r['planted']}\")")
ISSUES=$(python3 -c "import json;print(len(json.load(open('out/scene.json'))['issues']))")
say "checks passed — ${BYTES} bytes, recall ${RECALL}, ${ISSUES} issues"

if [ "$MODE" = "--local" ]; then
  say "serving http://localhost:8899  (ctrl-c to stop)"
  exec python3 -m http.server 8899 --directory out
fi

TARGET="--prod"
[ "$MODE" = "--preview" ] && TARGET=""
say "deploying to vercel ${TARGET:---preview}"
# CLI 54.x prints a JSON envelope, not a bare URL, so `| tail -1` yields
# a closing brace and every downstream check silently compares against
# nothing. Parse the field.
# shellcheck disable=SC2086
OUT=$(vercel deploy $TARGET --yes 2>/dev/null)
URL=$(printf '%s' "$OUT" | python3 -c '
import json, sys
raw = sys.stdin.read()
try:
    d = json.loads(raw[raw.index("{"):])
    print(d.get("deployment", {}).get("url", ""))
except Exception:
    # Older CLIs print the bare URL; fall back to the last https line.
    for ln in reversed(raw.splitlines()):
        if ln.strip().startswith("https://"):
            print(ln.strip()); break
')
[ -n "$URL" ] || { printf '%s\n' "$OUT"; die "could not read the deployment URL"; }
case "$URL" in https://*) ;; *) URL="https://$URL" ;; esac

say "verifying the deployed page, not just the upload"
sleep 2
BODY=$(curl -sL --max-time 30 "$URL")
LIVE=${#BODY}
# Not byte-equality: Vercel injects a toolbar attribute into preview HTML,
# so an exact match fails on every preview for a reason that has nothing
# to do with whether the page works. Check that what came back is the
# real page and roughly the right size.
# Herestrings, not pipes: `grep -q` matches, exits at once and closes the
# pipe, printf takes SIGPIPE, and `set -o pipefail` then reports the whole
# pipeline as failed *because* the match succeeded.
grep -q 'const THREE=' <<< "$BODY" \
  || die "served page has no three.js — protection page, or a stale alias"
grep -q 'scene-data' <<< "$BODY" \
  || die "served page has no scene data"
[ "$LIVE" -ge $((BYTES - 2000)) ] \
  || die "served only $LIVE bytes against $BYTES built — truncated"

printf '\n\033[32m✓ live\033[0m  %s\n' "$URL"
[ "$TARGET" = "--prod" ] && printf '  alias  https://access-twin.vercel.app\n'
printf '  audit  %s\n  film   %s#walkthrough\n' "$URL" "$URL"
