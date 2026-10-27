#!/usr/bin/env bash
# =============================================================================
#  UDYAT — Script para descargar de ToDus S3 SIN GASTAR MB de internet nacional
# =============================================================================
#
#  En Cuba, ETECSA factura el tráfico a internet "nacional" (extranjero).
#  Pero el servidor S3 de ToDus (s3.todus.cu) tiene una IP gratuita interna
#  (152.207.206.86) accesible desde la red cubana SIN consumo de megas.
#
#  Este script replica exactamente el comportamiento del sistema UDYAT
#  (decompilado de la app UDYAT-DOWN y portado a IroS3Dl):
#
#  1. Reescribe https://s3.todus.cu/... → https://152.207.206.86/...
#  2. Inyecta el header Host: s3.todus.cu (para que MinIO sepa qué vhost servir)
#  3. Inyecta el User-Agent: Wget/1.21.3 (igual que el sistema UDYAT original)
#  4. Desactiva la verificación TLS (--no-check-certificate) porque la IP
#     gratuita sirve un certificado self-signed para s3.todus.cu
#
#  Requisitos:
#    - wget (presente en Termux, la mayoría de distros Linux, macOS)
#    - Estar en la red cubana (la IP 152.207.206.86 solo responde desde Cuba)
#
#  Uso:
#    ./udyat_download.sh <URL_S3> [archivo_destino]
#
#  Ejemplos:
#    ./udyat_download.sh https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4
#    ./udyat_download.sh https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4 mi-pelicula.mp4
#    ./udyat_download.sh https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4 -  # a stdout
#
#  Test rápido (verificar que la IP gratuita responde):
#    ./udyat_download.sh --test
#
# =============================================================================
set -euo pipefail

# --- Configuración -----------------------------------------------------------
TODUS_HOST="s3.todus.cu"
FREE_IP="152.207.206.86"        # IP gratuita de ToDus (no gasta MB)
FREE_IP_BACKUP="152.207.206.88" # IP de respaldo (DNS actual)
USER_AGENT="Wget/1.21.3"        # UA exacto del sistema UDYAT
TIMEOUT=30                       # segundos para el pre-flight check

# --- Colores -----------------------------------------------------------------
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    RED='\033[0;31m'
    BLUE='\033[0;34m'
    NC='\033[0m'
else
    GREEN='' YELLOW='' RED='' BLUE='' NC=''
fi

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*" >&2; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*" >&2; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*" >&2; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# --- Test de conectividad ----------------------------------------------------
test_free_ip() {
    local ip="$1"
    log_info "Probando IP gratuita $ip..."
    local code
    code=$(curl -sS -o /dev/null -w "%{http_code}" \
        --max-time "$TIMEOUT" \
        --insecure \
        -H "Host: $TODUS_HOST" \
        -H "User-Agent: $USER_AGENT" \
        -I "https://$ip/" 2>/dev/null || echo "000")

    if [ "$code" != "000" ]; then
        log_ok "IP $ip responde (HTTP $code)"
        return 0
    else
        log_warn "IP $ip no responde"
        return 1
    fi
}

# --- Función principal -------------------------------------------------------
download_udyat() {
    local url="$1"
    local output="${2:-}"

    # Validar URL
    if [[ ! "$url" =~ ^https?://s3\.todus\.cu/stream/ ]]; then
        log_error "La URL debe ser de s3.todus.cu/stream/..."
        log_error "Ejemplo: https://s3.todus.cu/stream/users/df/7970466590/archivo.mp4"
        exit 1
    fi

    # Reescribir URL: s3.todus.cu → IP gratuita
    # Extraer el path después de /stream/
    local path
    path=$(echo "$url" | sed -E 's|^https?://s3\.todus\.cu||')
    local new_url="https://${FREE_IP}${path}"

    # Nombre del archivo de salida
    if [ -z "$output" ]; then
        # Default: basename de la URL, decodificado
        output=$(basename "$path" | python3 -c "
import sys, urllib.parse
print(urllib.parse.unquote(sys.stdin.read().strip()))
" 2>/dev/null || basename "$path")
    fi

    echo ""
    log_info "=== Sistema UDYAT — descarga sin gastar MB ==="
    log_info "URL original:  $url"
    log_info "URL reescrita: $new_url"
    log_info "Host header:   $TODUS_HOST"
    log_info "User-Agent:    $USER_AGENT"
    log_info "Archivo:       $output"
    echo ""

    # Pre-flight check: verificar que la IP gratuita responde
    log_info "Pre-flight check a $FREE_IP..."
    if ! test_free_ip "$FREE_IP"; then
        log_warn "IP principal no responde, probando backup $FREE_IP_BACKUP..."
        if test_free_ip "$FREE_IP_BACKUP"; then
            new_url="https://${FREE_IP_BACKUP}${path}"
            log_info "Usando IP de respaldo: $new_url"
        else
            log_error "Ninguna IP gratuita responde."
            log_error "Posibles causas:"
            log_error "  - No estás en la red cubana"
            log_error "  - ETECSA está bloqueando la IP"
            log_error "  - La IP ha cambiado (verificar con el bot @DkTodusbot)"
            log_error ""
            log_warn "Fallback: intentar con la URL original (consumirá MB)"
            new_url="$url"
        fi
    fi

    # Descargar con wget (igual que el script udyat-test.sh original)
    log_info "Iniciando descarga..."
    local wget_args=(
        --no-check-certificate
        --header="Host: $TODUS_HOST"
        --user-agent="$USER_AGENT"
        --continue
        --progress=bar:force
        --tries=3
        --timeout=60
    )

    if [ "$output" = "-" ]; then
        # stdout
        wget "${wget_args[@]}" -O - "$new_url"
    else
        wget "${wget_args[@]}" -O "$output" "$new_url"
    fi

    local status=$?
    if [ $status -eq 0 ]; then
        echo ""
        log_ok "Descarga completada: $output"
        if [ -f "$output" ]; then
            local size
            size=$(stat -c %s "$output" 2>/dev/null || stat -f %z "$output" 2>/dev/null || echo "?")
            log_ok "Tamaño: $size bytes ($((size / 1024 / 1024)) MB)"
        fi
    else
        echo ""
        log_error "Descarga falló (wget exit code: $status)"
        exit $status
    fi
}

# --- Modo test ---------------------------------------------------------------
run_test() {
    echo ""
    log_info "=== Test del sistema UDYAT ==="
    echo ""
    log_info "Probando IPs gratuitas de ToDus..."
    echo ""
    local any_ok=false
    for ip in "$FREE_IP" "$FREE_IP_BACKUP"; do
        if test_free_ip "$ip"; then
            any_ok=true
        fi
    done
    echo ""
    if [ "$any_ok" = "true" ]; then
        log_ok "Sistema UDYAT disponible — puedes descargar sin gastar MB"
        log_info "URLs válidas: https://s3.todus.cu/stream/..."
    else
        log_error "Sistema UDYAT no disponible desde tu red"
        log_warn "Posibles causas:"
        log_warn "  - No estás en la red cubana"
        log_warn "  - ETECSA está bloqueando las IPs gratuitas"
    fi
}

# --- Usage -------------------------------------------------------------------
usage() {
    cat <<EOF
${BLUE}UDYAT${NC} — Descarga de ToDus S3 sin gastar MB

${BLUE}USO:${NC}
  $0 <URL_S3> [archivo_destino]
  $0 --test
  $0 --help

${BLUE}OPCIONES:${NC}
  --test       Probar conectividad a las IPs gratuitas
  --help       Mostrar esta ayuda

${BLUE}EJEMPLOS:${NC}
  # Descargar un archivo
  $0 https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4

  # Con nombre de archivo custom
  $0 https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4 mi-pelicula.mp4

  # A stdout (para pipe)
  $0 https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4 - | mpv -

  # Test de conectividad
  $0 --test

${BLUE}CÓMO FUNCIONA:${NC}
  1. Reescribe s3.todus.cu → 152.207.206.86 (IP gratuita de ToDus)
  2. Inyecta header Host: s3.todus.cu (vhost)
  3. Inyecta User-Agent: Wget/1.21.3
  4. Desactiva verificación TLS (cert self-signed)
  5. Si la IP principal no responde, prueba la backup (152.207.206.88)

${BLUE}REQUISITOS:${NC}
  - wget
  - Estar en la red cubana (las IPs solo responden desde Cuba)
EOF
}

# --- Main --------------------------------------------------------------------
case "${1:-}" in
    --help|-h)
        usage
        ;;
    --test)
        run_test
        ;;
    "")
        usage
        exit 1
        ;;
    *)
        download_udyat "$@"
        ;;
esac
