# -*- coding: utf-8 -*-
"""UDYAT — Descarga de ToDus S3 SIN GASTAR MB de internet nacional.

En Cuba, ETECSA factura el tráfico a internet "nacional" (extranjero).
Pero el servidor S3 de ToDus (s3.todus.cu) tiene una IP gratuita interna
(152.207.206.86) accesible desde la red cubana SIN consumo de megas.

Este script replica el comportamiento del sistema UDYAT (decompilado de
la app UDYAT-DOWN y portado a IroS3Dl):

1. Reescribe https://s3.todus.cu/... → https://152.207.206.86/...
2. Inyecta el header Host: s3.todus.cu (para que MinIO sepa qué vhost servir)
3. Inyecta el User-Agent: Wget/1.21.3 (igual que el sistema UDYAT original)
4. Desactiva la verificación TLS (verify=False) porque la IP gratuita
   sirve un certificado self-signed para s3.todus.cu
5. Pre-flight check HEAD 3s a la IP gratuita antes de descargar
6. Fallback automático a la IP de respaldo (152.207.206.88) si la principal
   no responde
7. Soporta descarga multi-hilo con Range (más rápida)

Requisitos:
    pip install requests

Uso:
    python udyat_download.py <URL_S3> [archivo_destino] [--threads N] [--test]

Ejemplos:
    # Descargar un archivo
    python udyat_download.py https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4

    # Con nombre custom
    python udyat_download.py https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4 mi-pelicula.mp4

    # Multi-hilo (4 conexiones paralelas con Range)
    python udyat_download.py https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4 --threads 4

    # Test de conectividad
    python udyat_download.py --test
"""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import sys
import time
from urllib.parse import unquote, urlparse

import requests
import urllib3

# Suprimir warning de TLS self-signed
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Configuración UDYAT ─────────────────────────────────────────────────
TODUS_HOST = "s3.todus.cu"
FREE_IP_PRIMARY = "152.207.206.86"   # IP gratuita clásica de ToDus
FREE_IP_BACKUP = "152.207.206.88"    # DNS actual (respaldo)
USER_AGENT = "Wget/1.21.3"            # UA exacto del sistema UDYAT
CHUNK_SIZE = 1024 * 1024              # 1 MB
TIMEOUT = 30                          # segundos para pre-flight check


# ─── Colores ─────────────────────────────────────────────────────────────
class C:
    GREEN = "\033[0;32m" if sys.stderr.isatty() else ""
    YELLOW = "\033[0;33m" if sys.stderr.isatty() else ""
    RED = "\033[0;31m" if sys.stderr.isatty() else ""
    BLUE = "\033[0;34m" if sys.stderr.isatty() else ""
    NC = "\033[0m" if sys.stderr.isatty() else ""


def log_info(msg): print(f"{C.BLUE}[INFO]{C.NC}  {msg}", file=sys.stderr)
def log_ok(msg): print(f"{C.GREEN}[OK]{C.NC}    {msg}", file=sys.stderr)
def log_warn(msg): print(f"{C.YELLOW}[WARN]{C.NC}  {msg}", file=sys.stderr)
def log_error(msg): print(f"{C.RED}[ERROR]{C.NC} {msg}", file=sys.stderr)


# ─── Helpers ─────────────────────────────────────────────────────────────
def rewrite_url(url: str, ip: str) -> str:
    """Reescribe https://s3.todus.cu/... → https://<ip>/..."""
    parsed = urlparse(url)
    return f"https://{ip}{parsed.path}" + (f"?{parsed.query}" if parsed.query else "")


def udyat_headers() -> dict:
    """Cabeceras exactas del sistema UDYAT."""
    return {
        "Host": TODUS_HOST,
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }


def test_free_ip(ip: str, timeout: int = TIMEOUT) -> bool:
    """Pre-flight check HEAD 3s a la IP gratuita."""
    log_info(f"Probando IP gratuita {ip}...")
    try:
        resp = requests.head(
            f"https://{ip}/",
            headers=udyat_headers(),
            verify=False,
            timeout=timeout,
        )
        log_ok(f"IP {ip} responde (HTTP {resp.status_code})")
        return True
    except requests.RequestException as e:
        log_warn(f"IP {ip} no responde: {type(e).__name__}")
        return False


def select_free_ip() -> str | None:
    """Selecciona la IP gratuita que responde. Devuelve None si ninguna."""
    if test_free_ip(FREE_IP_PRIMARY):
        return FREE_IP_PRIMARY
    log_warn(f"IP principal {FREE_IP_PRIMARY} no responde, probando backup {FREE_IP_BACKUP}...")
    if test_free_ip(FREE_IP_BACKUP):
        return FREE_IP_BACKUP
    return None


# ─── Descarga ────────────────────────────────────────────────────────────
def get_file_size(url: str, ip: str) -> int:
    """HEAD para obtener el tamaño del archivo."""
    new_url = rewrite_url(url, ip)
    resp = requests.head(
        new_url,
        headers=udyat_headers(),
        verify=False,
        timeout=30,
    )
    if resp.status_code != 200:
        raise SystemExit(f"HEAD falló: HTTP {resp.status_code}")
    return int(resp.headers.get("Content-Length", "0") or "0")


def download_single(url: str, ip: str, output_path: str, total_size: int):
    """Descarga en un solo hilo con streaming."""
    new_url = rewrite_url(url, ip)
    headers = udyat_headers()

    resp = requests.get(
        new_url,
        headers=headers,
        verify=False,
        stream=True,
        timeout=3600,
    )
    if resp.status_code != 200:
        raise SystemExit(f"GET falló: HTTP {resp.status_code}")

    done = 0
    t0 = time.time()
    last_report = 0.0
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(CHUNK_SIZE):
            if not chunk:
                continue
            f.write(chunk)
            done += len(chunk)
            now = time.time()
            if now - last_report > 0.6 or done >= total_size:
                last_report = now
                elapsed = now - t0
                speed = (done / elapsed / (1024 * 1024)) if elapsed > 0 else 0.0
                pct = (done / total_size * 100) if total_size else 0
                sys.stderr.write(
                    f"\r  {pct:.1f}%  {done/1024/1024:.1f}/{total_size/1024/1024:.1f} MB  {speed:.2f} MB/s"
                )
                sys.stderr.flush()
    sys.stderr.write("\n")


def download_multithread(url: str, ip: str, output_path: str, total_size: int, threads: int):
    """Descarga multi-hilo usando Range. Más rápida para archivos grandes."""
    new_url = rewrite_url(url, ip)
    headers = udyat_headers()
    chunk_size = total_size // threads
    parts = []

    def _download_chunk(idx: int, start: int, end: int) -> int:
        part_path = f"{output_path}.part{idx}"
        parts.append((idx, part_path))
        h = {**headers, "Range": f"bytes={start}-{end}"}
        resp = requests.get(new_url, headers=h, verify=False, stream=True, timeout=3600)
        if resp.status_code != 206:
            raise SystemExit(f"Range request falló: HTTP {resp.status_code}")
        with open(part_path, "wb") as f:
            for chunk in resp.iter_content(CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
        return os.path.getsize(part_path)

    log_info(f"Descargando en {threads} hilos paralelos...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as exe:
        futures = []
        for i in range(threads):
            start = i * chunk_size
            end = (start + chunk_size - 1) if i < threads - 1 else total_size - 1
            futures.append(exe.submit(_download_chunk, i, start, end))
        done = 0
        t0 = time.time()
        last_report = 0.0
        for fut in concurrent.futures.as_completed(futures):
            done += fut.result()
            now = time.time()
            if now - last_report > 0.6:
                last_report = now
                elapsed = now - t0
                speed = (done / elapsed / (1024 * 1024)) if elapsed > 0 else 0.0
                pct = (done / total_size * 100) if total_size else 0
                sys.stderr.write(
                    f"\r  {pct:.1f}%  {done/1024/1024:.1f}/{total_size/1024/1024:.1f} MB  {speed:.2f} MB/s"
                )
                sys.stderr.flush()

    sys.stderr.write("\n")
    log_info("Uniendo partes...")
    with open(output_path, "wb") as out:
        for idx, part_path in sorted(parts):
            with open(part_path, "rb") as p:
                while True:
                    chunk = p.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
            try:
                os.unlink(part_path)
            except OSError:
                pass


def download(url: str, output: str | None = None, threads: int = 1):
    """Función principal de descarga UDYAT."""
    # Validar URL
    if "s3.todus.cu/stream/" not in url:
        log_error("La URL debe ser de s3.todus.cu/stream/...")
        log_error("Ejemplo: https://s3.todus.cu/stream/users/df/7970466590/archivo.mp4")
        sys.exit(1)

    # Nombre de archivo default
    if not output:
        path = urlparse(url).path
        output = unquote(os.path.basename(path))

    # Seleccionar IP gratuita
    ip = select_free_ip()
    if not ip:
        log_error("Ninguna IP gratuita responde.")
        log_error("Posibles causas:")
        log_error("  - No estás en la red cubana")
        log_error("  - ETECSA está bloqueando las IPs")
        log_error("  - Las IPs han cambiado (verificar con el bot @DkTodusbot)")
        log_error("")
        log_warn("Fallback: usar URL original (consumirá MB)")
        ip = TODUS_HOST

    echo = ""
    print(f"\n{C.BLUE}=== Sistema UDYAT — descarga sin gastar MB ==={C.NC}", file=sys.stderr)
    log_info(f"URL original:  {url}")
    log_info(f"URL reescrita: {rewrite_url(url, ip)}")
    log_info(f"Host header:   {TODUS_HOST}")
    log_info(f"User-Agent:    {USER_AGENT}")
    log_info(f"Archivo:       {output}")
    if threads > 1:
        log_info(f"Hilos:         {threads}")
    print("", file=sys.stderr)

    # Obtener tamaño
    try:
        total_size = get_file_size(url, ip)
        log_ok(f"Tamaño: {total_size} bytes ({total_size/1024/1024:.2f} MB)")
    except SystemExit as e:
        log_error(f"No se pudo obtener tamaño: {e}")
        sys.exit(1)

    # Descargar
    log_info("Iniciando descarga...")
    try:
        if threads > 1 and total_size > 0:
            # Verificar que soporta rangos
            new_url = rewrite_url(url, ip)
            resp = requests.head(new_url, headers=udyat_headers(), verify=False, timeout=30)
            if resp.headers.get("Accept-Ranges") == "bytes":
                download_multithread(url, ip, output, total_size, threads)
            else:
                log_warn("Servidor no soporta rangos, usando 1 hilo")
                download_single(url, ip, output, total_size)
        else:
            download_single(url, ip, output, total_size)
    except KeyboardInterrupt:
        log_error("\nDescarga interrumpida por el usuario")
        sys.exit(130)

    print("", file=sys.stderr)
    log_ok(f"Descarga completada: {output}")
    if os.path.exists(output):
        size = os.path.getsize(output)
        log_ok(f"Tamaño final: {size} bytes ({size/1024/1024:.2f} MB)")


# ─── Test ────────────────────────────────────────────────────────────────
def run_test():
    """Test de conectividad a las IPs gratuitas."""
    print(f"\n{C.BLUE}=== Test del sistema UDYAT ==={C.NC}\n", file=sys.stderr)
    log_info("Probando IPs gratuitas de ToDus...\n")
    any_ok = False
    for ip in [FREE_IP_PRIMARY, FREE_IP_BACKUP]:
        if test_free_ip(ip):
            any_ok = True
    print("", file=sys.stderr)
    if any_ok:
        log_ok("Sistema UDYAT disponible — puedes descargar sin gastar MB")
        log_info("URLs válidas: https://s3.todus.cu/stream/...")
    else:
        log_error("Sistema UDYAT no disponible desde tu red")
        log_warn("Posibles causas:")
        log_warn("  - No estás en la red cubana")
        log_warn("  - ETECSA está bloqueando las IPs gratuitas")


# ─── CLI ─────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(
        description="UDYAT — Descarga de ToDus S3 sin gastar MB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Descargar un archivo
  %(prog)s https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4

  # Con nombre custom
  %(prog)s https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4 mi-pelicula.mp4

  # Multi-hilo (4 conexiones con Range)
  %(prog)s https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4 --threads 4

  # Test de conectividad
  %(prog)s --test
""",
    )
    p.add_argument("url", nargs="?", help="URL del archivo en s3.todus.cu/stream/...")
    p.add_argument("output", nargs="?", help="archivo de salida (default: basename de la URL)")
    p.add_argument("--threads", type=int, default=1,
                   help="número de hilos paralelos (multi-hilo con Range, default 1)")
    p.add_argument("--test", action="store_true",
                   help="probar conectividad a las IPs gratuitas")
    args = p.parse_args()

    if args.test:
        run_test()
        return

    if not args.url:
        p.print_help()
        sys.exit(1)

    download(args.url, args.output, args.threads)


if __name__ == "__main__":
    main()
