#!/usr/bin/env bash
# Verifies the APIM chat and embedding endpoints respond. Reads .env; prints status only, never the key.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

: "${AZURE_APIM_BASE_URL:?set in .env}" "${AZURE_APIM_KEY:?set in .env}"
: "${AZURE_CHAT_PATH:?set in .env}" "${AZURE_EMBED_PATH:?set in .env}"

call() {
  local name=$1 path=$2 body=$3
  local code
  code=$(curl -sS -o /tmp/apim_$name.json -w '%{http_code}' --max-time 30 \
    -H "Ocp-Apim-Subscription-Key: $AZURE_APIM_KEY" -H 'Content-Type: application/json' \
    -d "$body" "$AZURE_APIM_BASE_URL$path")
  echo "$name -> HTTP $code"
  head -c 300 /tmp/apim_$name.json; echo
}

call chat  "$AZURE_CHAT_PATH"  '{"messages":[{"role":"user","content":"Say hi"}],"max_tokens":16}'
call embed "$AZURE_EMBED_PATH" '{"input":"hello world"}'
