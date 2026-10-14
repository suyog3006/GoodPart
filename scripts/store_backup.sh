#!/usr/bin/env sh
# Save every station (database, good photos, inspections and trained memory banks) to this computer,
# so stations survive destroying the GPU droplet. Restore with scripts/store_restore.sh.
#   scripts/store_backup.sh [host]              user stations only (small)
#   WITH_SHOWCASE=1 scripts/store_backup.sh     also the two ~2.5 GB showcase stations
# The per-category evaluation stations (visa_<category>_k*.pkl) are not copied; the evaluation recreates them.
set -e
HOST=${1:-${GOODPART_HOST:-root@134.199.202.180}}
OUT=${GOODPART_BACKUP:-$HOME/goodpart_data/store_backup}
mkdir -p "$OUT"
EXCL="--exclude=stations/visa_*"
[ "${WITH_SHOWCASE:-0}" = "1" ] || EXCL="$EXCL --exclude=stations/visa-*.pkl"
ssh -o BatchMode=yes "$HOST" "docker exec gp python3 -c \"import sqlite3; s=sqlite3.connect('/data/store/goodpart.db'); s.execute('PRAGMA wal_checkpoint(FULL)'); s.close()\" 2>/dev/null; cd /root/data/store && tar -czf - $EXCL ." \
  | tar -xzf - -C "$OUT"
echo "Backed up to $OUT:"; du -sh "$OUT"
