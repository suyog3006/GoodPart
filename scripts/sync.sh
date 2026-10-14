#!/usr/bin/env sh
# Copy the code (not data, not secrets) to the AMD GPU droplet. Usage: scripts/sync.sh [host]
HOST=${1:-${GOODPART_HOST:-root@134.199.202.180}}
tar -czf - --exclude=.git --exclude=results --exclude=web/node_modules --exclude=web/.next \
  --exclude=.env --exclude='*.pyc' --exclude=__pycache__ goodpart configs scripts \
  | ssh -o BatchMode=yes "$HOST" 'mkdir -p /root/goodpart && tar -xzf - -C /root/goodpart'
