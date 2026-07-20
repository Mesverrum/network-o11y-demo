#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
find . \( -name '*.sh' -o -name '*.env' -o -name '*.env.sample' -o -name 'Makefile' -o -name '*.tmpl' \) \
  -print0 | xargs -0 sed -i 's/\r$//'
cp groups/srl.env.sample groups/srl.env
sed -i 's/\r$//' groups/srl.env
./scripts/generate-groups.sh
echo "--- compose-groups head ---"
head -50 compose-groups.generated.yaml
echo "--- poller ---"
head -25 config/poller-srl.yaml
echo "--- discovery ---"
head -30 config/discovery-srl.yaml
