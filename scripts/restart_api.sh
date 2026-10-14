#!/usr/bin/env sh
# Restart the GoodPart API inside the gp container on the droplet: exactly one process, never stuck.
#   scripts/restart_api.sh [host]
HOST=${1:-${GOODPART_HOST:-root@134.199.202.180}}
ssh -o BatchMode=yes "$HOST" '
docker exec gp pkill -9 -f "uvicorn goodpart.api" ; sleep 1
docker exec -d gp bash -lc "cd /workspace/goodpart && set -a && . ./.env && set +a && \
  exec uvicorn goodpart.api.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 3 > results/api.log 2>&1"
for i in $(seq 1 90); do curl -s -m 3 localhost:8000/health >/dev/null && break; sleep 2; done
echo "API processes: $(docker exec gp pgrep -fc "uvicorn goodpart.api")"; curl -s localhost:8000/health; echo'
