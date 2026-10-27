#!/usr/bin/env bash
# Subida a ToDus S3 con reintentos y validación HEAD posterior.
# USA FORMATO PERSISTENTE: users/df/<user_id>/  (ver README §2)
#
# Uso: ./curl_with_retry.sh <archivo> <user_id>
set -euo pipefail

BASE="https://s3.todus.cu/stream"
FILE="${1:?uso: $0 <archivo> <user_id>}"
USER_ID="${2:?uso: $0 <archivo> <user_id>}"

# FORMATO PERSISTENTE: users/df/<user_id>/
# El formato users/tg_<user_id>/ SE BORRA automáticamente por MinIO.
FOLDER="users/df/${USER_ID}"

NAME="$(basename "$FILE")"
URL="$BASE/$FOLDER/$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=''))" "$NAME")"
RETRIES=3

echo "Subiendo a: $URL"
for i in $(seq 1 "$RETRIES"); do
  # Capturar status + etag + rate-limit en una sola petición
  RESPONSE=$(curl -sS -o /tmp/put_body -w "%{http_code}\n%{header_json}" -X PUT \
      --data-binary "@$FILE" \
      -H "Content-Type: application/octet-stream" \
      "$URL" 2>/dev/null || echo "000")
  CODE=$(echo "$RESPONSE" | head -1)

  if [ "$CODE" = "200" ] || [ "$CODE" = "201" ] || [ "$CODE" = "204" ]; then
    ETAG=$(echo "$RESPONSE" | python3 -c "import sys, json; d=json.load(sys.stdin); print([v[0] for k,v in d.items() if k.lower()=='etag'][0] if any(k.lower()=='etag' for k in d) else '')" 2>/dev/null || echo "")
    RL_REMAINING=$(echo "$RESPONSE" | python3 -c "import sys, json; d=json.load(sys.stdin); print([v[0] for k,v in d.items() if k.lower()=='x-ratelimit-remaining'][0] if any(k.lower()=='x-ratelimit-remaining' for k in d) else '')" 2>/dev/null || echo "")
    echo "PUT OK ($CODE)"
    [ -n "$ETAG" ] && echo "ETag: $ETAG"
    [ -n "$RL_REMAINING" ] && echo "Rate limit remaining: $RL_REMAINING"
    break
  fi
  WAIT=$((2 ** (i-1) > 8 ? 8 : 2 ** (i-1)))
  echo "Intento $i falló (HTTP $CODE). Reintentando en ${WAIT}s..."
  sleep "$WAIT"
  [ "$i" = "$RETRIES" ] && { echo "Falló definitivamente"; exit 1; }
done

echo "Verificando con HEAD..."
sleep 0.5
head_code="$(curl -sS -o /dev/null -w "%{http_code}" -I "$URL" || echo 000)"
if [ "$head_code" = "200" ]; then
  echo "✅ Archivo confirmado en S3: $URL"
else
  echo "⚠️  HEAD devolvió $head_code — posible borrado por whitelist de prefijo"
  exit 1
fi
