#!/usr/bin/env sh
# Put stations saved by scripts/store_backup.sh onto a (new) GPU droplet, then restart the API there.
#   scripts/store_restore.sh [host]
set -e
HOST=${1:-${GOODPART_HOST:-root@134.199.202.180}}
SRC=${GOODPART_BACKUP:-$HOME/goodpart_data/store_backup}
[ -f "$SRC/goodpart.db" ] || { echo "No backup found in $SRC"; exit 1; }
tar -czf - -C "$SRC" . | ssh -o BatchMode=yes "$HOST" 'mkdir -p /root/data/store && tar -xzf - -C /root/data/store'
echo "Restored to $HOST:/root/data/store. Restart the API so it loads the stations."
