# -*- coding: utf-8 -*-
"""Descarga de un archivo del bucket público de ToDus S3.

Soporta:
- Descarga simple (1 hilo)
- Descarga multi-hilo con Range (para archivos grandes)
- Reanudar descarga parcial (con --resume)
- Verificación de integridad con ETag

Uso: python python_download.py <url> <output> [--threads N] [--resume]
"""
import argparse
import concurrent.futures
import os
import sys
import time

import requests

BASE = "https://s3.todus.cu/stream"
CHUNK = 1024 * 1024  # 1 MB
TIMEOUT = 3600


def head(url):
    """HEAD para obtener tamaño, ETag y si soporta rangos."""
    resp = requests.head(url, timeout=30)
    if resp.status_code != 200:
        return None
    return {
        "size": int(resp.headers.get("Content-Length", "0") or "0"),
        "etag": resp.headers.get("ETag", "").strip('"'),
        "accept_ranges": resp.headers.get("Accept-Ranges") == "bytes",
        "last_modified": resp.headers.get("Last-Modified", ""),
    }


def download_single(url, output_path, total_size, progress=None):
    """Descarga en un solo hilo."""
    resp = requests.get(url, stream=True, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise SystemExit(f"HTTP {resp.status_code}: {resp.text[:200]}")

    done = 0
    t0 = time.time()
    last_report = 0.0
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(CHUNK):
            if not chunk:
                continue
            f.write(chunk)
            done += len(chunk)
            if progress and (time.time() - last_report > 0.6 or done >= total_size):
                last_report = time.time()
                elapsed = time.time() - t0
                speed = done / elapsed / (1024 * 1024) if elapsed > 0 else 0.0
                progress(done, total_size, speed)
    return output_path


def download_multithread(url, output_path, total_size, threads, progress=None):
    """Descarga multi-hilo usando Range.

    Requiere que el servidor soporte Accept-Ranges (sí lo hace ToDus).
    """
    chunk_size = total_size // threads
    parts = []

    def _download_chunk(idx, start, end):
        part_path = f"{output_path}.part{idx}"
        parts.append((idx, part_path))
        headers = {"Range": f"bytes={start}-{end}"}
        resp = requests.get(url, headers=headers, stream=True, timeout=TIMEOUT)
        if resp.status_code != 206:
            raise SystemExit(f"Range request falló: HTTP {resp.status_code}")
        with open(part_path, "wb") as f:
            for chunk in resp.iter_content(CHUNK):
                if chunk:
                    f.write(chunk)
        return os.path.getsize(part_path)

    print(f"Descargando en {threads} hilos...", file=sys.stderr)
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as exe:
        futures = []
        for i in range(threads):
            start = i * chunk_size
            end = (start + chunk_size - 1) if i < threads - 1 else total_size - 1
            futures.append(exe.submit(_download_chunk, i, start, end))
        done = 0
        for fut in concurrent.futures.as_completed(futures):
            done += fut.result()
            if progress:
                progress(done, total_size, 0.0)

    # Unir partes en orden
    print("Uniendo partes...", file=sys.stderr)
    with open(output_path, "wb") as out:
        for idx, part_path in sorted(parts):
            with open(part_path, "rb") as p:
                while True:
                    chunk = p.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
            try:
                os.unlink(part_path)
            except OSError:
                pass
    return output_path


def verify_etag(url, output_path, expected_etag):
    """Verifica que el ETag del archivo descargado coincida con el del servidor.

    Nota: Para archivos grandes subidos con multipart, el ETag no es un MD5 simple.
    """
    import hashlib
    h = hashlib.md5()
    with open(output_path, "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
    actual_md5 = h.hexdigest()
    if expected_etag and "-" not in expected_etag:
        # ETag sin guion = MD5 simple
        if actual_md5 == expected_etag:
            print(f"✅ ETag verificado: {actual_md5}", file=sys.stderr)
            return True
        else:
            print(f"⚠️  ETag no coincide: esperado={expected_etag} actual={actual_md5}", file=sys.stderr)
            return False
    elif expected_etag:
        print(f"ℹ️  ETag multipart (no se puede verificar con MD5 simple): {expected_etag}", file=sys.stderr)
    return True


def main():
    p = argparse.ArgumentParser(description="Descargar archivo del bucket ToDus S3")
    p.add_argument("url", help="URL del archivo")
    p.add_argument("output", help="ruta de salida")
    p.add_argument("--threads", type=int, default=1,
                   help="número de hilos (multi-hilo con Range, default 1)")
    p.add_argument("--resume", action="store_true",
                   help="reanudar descarga parcial si existe .partN")
    p.add_argument("--no-verify", action="store_true",
                   help="no verificar ETag al final")
    args = p.parse_args()

    print(f"HEAD {args.url}...", file=sys.stderr)
    info = head(args.url)
    if not info:
        print(f"❌ El archivo no existe o no es accesible", file=sys.stderr)
        sys.exit(1)

    print(f"Tamaño: {info['size']} bytes ({info['size']/1024/1024:.2f} MB)", file=sys.stderr)
    print(f"ETag: {info['etag']}", file=sys.stderr)
    print(f"Accept-Ranges: {info['accept_ranges']}", file=sys.stderr)
    print(f"Last-Modified: {info['last_modified']}", file=sys.stderr)
    print(file=sys.stderr)


    def prog(done, total, speed):
        pct = (done / total * 100) if total else 0
        print(f"\r  {pct:.1f}%  {done/1024/1024:.1f}/{total/1024/1024:.1f} MB  {speed:.2f} MB/s",
              end="", flush=True, file=sys.stderr)


    if args.threads > 1 and info["accept_ranges"] and info["size"] > 0:
        download_multithread(args.url, args.output, info["size"], args.threads, progress=prog)
    else:
        download_single(args.url, args.output, info["size"], progress=prog)

    print(f"\n✅ Descargado: {args.output}", file=sys.stderr)

    # Verificar ETag
    if not args.no_verify and info["etag"]:
        verify_etag(args.url, args.output, info["etag"])


if __name__ == "__main__":
    main()
