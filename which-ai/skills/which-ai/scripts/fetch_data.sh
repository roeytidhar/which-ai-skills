#!/usr/bin/env bash
# Usage: fetch_data.sh <text|coding|vision> [out_dir]
set -u
MOD=${1:-text}; OUT=${2:-.}
case "$MOD" in vision) CFG=vision;; *) CFG=text;; esac
mkdir -p "$OUT"; rm -f "$OUT"/arena_*.json "$OUT"/arena.parquet
curl -sS --max-time 30 --retry 2 "https://openrouter.ai/api/v1/models" -o "$OUT/openrouter_data.json" || echo "openrouter download failed"
curl -sSL --max-time 60 --retry 2 \
  "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset/resolve/main/$CFG/latest-00000-of-00001.parquet" \
  -o "$OUT/arena.parquet"
python3 -c "import pyarrow" 2>/dev/null || python3 -m pip install -q --user pyarrow 2>/dev/null \
  || python3 -m pip install -q --break-system-packages pyarrow 2>/dev/null
if python3 -c "import pyarrow.parquet as pq; assert pq.read_table('$OUT/arena.parquet').num_rows > 0" 2>/dev/null; then
  echo "arena: $OUT/arena.parquet ($CFG)"; exit 0
fi
rm -f "$OUT/arena.parquet"
case "$MOD" in coding) CAT=coding;; *) CAT=overall;; esac
off=0
while [ $off -lt 1000 ]; do
  f="$OUT/arena_${off}.json"; n=-1
  for try in 1 2 3; do
    curl -sS --max-time 60 -G "https://datasets-server.huggingface.co/filter" \
      --data-urlencode "dataset=lmarena-ai/leaderboard-dataset" --data-urlencode "config=$CFG" \
      --data-urlencode "split=latest" --data-urlencode "where=\"category\"='$CAT'" \
      --data-urlencode "offset=$off" --data-urlencode "length=100" -o "$f"
    n=$(python3 -c "import json,sys
try: d=json.load(open('$f'))
except Exception: print(-1); sys.exit()
print(len(d['rows']) if 'rows' in d else -1)")
    [ "$n" -ge 0 ] && break; sleep 2
  done
  [ "$n" -lt 0 ] && { echo "arena page at offset $off failed: $(head -c 200 "$f")"; rm -f "$f"; break; }
  [ "$n" -lt 100 ] && break
  off=$((off+100))
done
echo "arena: $(ls "$OUT"/arena_*.json 2>/dev/null | wc -l) JSON page(s) ($CFG/$CAT)"
