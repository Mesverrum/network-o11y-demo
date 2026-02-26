#!/usr/bin/env bash
# Source this file to export AWS credentials as environment variables.
# Usage: source scripts/setup-env.sh
#
# The script reads from aws.credentials in the repo root, which is gitignored.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREDS_FILE="$SCRIPT_DIR/../aws.credentials"
PROFILE="494614287886_AdministratorAccess"

if [[ ! -f "$CREDS_FILE" ]]; then
  echo "ERROR: $CREDS_FILE not found. Place your AWS credentials file there." >&2
  return 1
fi

_extract() {
  awk -F= "/\\[$PROFILE\\]/{found=1} found && /^$1/{gsub(/ /, \"\", \$2); print \$2; exit}" "$CREDS_FILE"
}

export AWS_ACCESS_KEY_ID="$(_extract aws_access_key_id)"
export AWS_SECRET_ACCESS_KEY="$(_extract aws_secret_access_key)"
export AWS_SESSION_TOKEN="$(_extract aws_session_token)"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-eu-west-1}"

echo "✓ AWS credentials loaded  (account key: ${AWS_ACCESS_KEY_ID:0:12}...)"
echo "✓ Region: $AWS_DEFAULT_REGION"
