#!/usr/bin/env bash
# Subida a ToDus S3 con reintentos y validación HEAD posterior.
# Uso: ./curl_with_retry.sh <archivo> [carpeta]
set -euo pipefail

BASE="https://s3.todus.cu/stream"
FILE="${1:?uso: $0 <archivo> [carpeta]}"
FOLDER="${2:-GRATIS/tg_prueba}"
NAME="$(basename "$FILE")"
URL="$BASE/$FOLDER/$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=''))" "$NAME")"
RETRIES=3

echo "Subiendo a: $URL"
for i in $(seq 1 "$RETRIES"); do
  code="$(curl -sS -o /dev/null -w "%{http_code}" -X PUT \
      --data-binary "@$FILE" \
      -H "Content-Type: application/octet-stream" \
      "$URL" || echo 000)"
  if [ "$code" = "200" ] || [ "$code" = "201" ] || [ "$code" = "204" ]; then
    echo "PUT OK ($code)"
    break
  fi
  echo "Intento $i falló (HTTP $code). Reintentando en $((2 ** (i-1)))s..."; sleep "$((2 ** (i-1) > 8 ? 8 : 2 ** (i-1)))"
  [ "$i" = "$RETRIES" ] && { echo "Falló definitivamente"; exit 1; }
done

echo "Verificando con HEAD..."
head_code="$(curl -sS -o /dev/null -w "%{http_code}" -I "$URL" || echo 000)"
[ "$head_code" = "200" ] && echo "✅ Archivo confirmado en S3: $URL" || { echo "⚠️  HEAD devolvió $head_code"; exit 1; }
