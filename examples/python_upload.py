# -*- coding: utf-8 -*-
"""Ejemplo de subida anónima a ToDus S3 con requests.

USO DEL FORMATO PERSISTENTE: users/df/<user_id>/  (ver README §2)

Uso: python python_upload.py <ruta_archivo> <user_id>
"""
import os
import sys
import time
from urllib.parse import quote

import requests

BASE = "https://s3.todus.cu/stream"
CHUNK = 1024 * 1024  # 1 MB
TIMEOUT = 3600
RETRIES = 3


class ProgressReader:
    def __init__(self, path, progress=None):
        self.f = open(path, "rb")
        self.total = os.path.getsize(path)
        self.progress = progress
        self.sent = 0
        self.t0 = time.time()
        self.last_report = 0.0

    def read(self, size=-1):
        chunk = self.f.read(size)
        if chunk and self.progress is not None:
            self.sent += len(chunk)
            now = time.time()
            if now - self.last_report > 0.6 or self.sent >= self.total:
                self.last_report = now
                elapsed = now - self.t0
                speed = self.sent / elapsed / (1024 * 1024) if elapsed > 0 else 0.0
                self.progress(self.sent, self.total, speed)
        return chunk

    def close(self):
        self.f.close()

    def rewind(self):
        self.f.seek(0)
        self.sent = 0
        self.t0 = time.time()
        self.last_report = 0.0


def folder_for_user(user_id):
    """FORMATO PERSISTENTE: users/df/<user_id>/

    El formato users/tg_<user_id>/ SE BORRA automáticamente por MinIO.
    Ver README §2 para más detalles.
    """
    return f"users/df/{user_id}"


def upload(path, user_id, progress=None, retries=RETRIES, timeout=TIMEOUT, verify=True):
    """Sube un archivo bajo users/df/<user_id>/.

    Args:
        path: ruta local del archivo
        user_id: ID numérico del usuario
        progress: callback(done, total, speed_mbs)
        retries: número de reintentos
        timeout: timeout en segundos
        verify: hacer HEAD después del PUT para confirmar

    Returns:
        (url, seconds, etag) o lanza SystemExit
    """
    size = os.path.getsize(path)
    name = os.path.basename(path)
    safe_name = quote(name, safe="")
    folder = folder_for_user(user_id)
    url = f"{BASE}/{folder}/{safe_name}"
    session = requests.Session()
    reader = ProgressReader(path, progress)
    t0 = time.time()
    last_error = None
    etag = None
    try:
        for attempt in range(1, retries + 1):
            reader.rewind()
            try:
                resp = session.put(
                    url,
                    data=reader,
                    headers={
                        "Content-Length": str(size),
                        "Content-Type": "application/octet-stream",
                    },
                    timeout=timeout,
                )
                etag = resp.headers.get("ETag")

                # Capturar rate-limit si está disponible
                rl_remaining = resp.headers.get("x-ratelimit-remaining")
                if rl_remaining:
                    print(f"  Rate limit remaining: {rl_remaining}", file=sys.stderr)

                if resp.status_code >= 500 or resp.status_code == 429:
                    last_error = f"HTTP {resp.status_code}"
                    if attempt < retries:
                        wait = min(30.0, 2.0 ** (attempt - 1))
                        print(f"  Intento {attempt} falló ({last_error}). Reintentando en {wait:.0f}s...", file=sys.stderr)
                        time.sleep(wait)
                        continue
                    raise SystemExit(f"Fallo tras reintentos: {last_error}")
                if resp.status_code not in (200, 201, 204):
                    raise SystemExit(f"HTTP {resp.status_code}: {resp.text[:200]}")
                dt = max(0.001, time.time() - t0)
                if progress:
                    progress(size, size, size / dt / (1024 * 1024))

                # Verificar con HEAD que el archivo quedó persistido
                if verify:
                    time.sleep(0.5)
                    head = session.head(url, timeout=30)
                    if head.status_code != 200:
                        raise SystemExit(
                            f"PUT OK pero HEAD dice {head.status_code}. "
                            f"Posible borrado por whitelist de prefijo."
                        )

                return url, dt, etag
            except (requests.ConnectionError, requests.Timeout) as err:
                last_error = str(err)
                if attempt < retries:
                    wait = min(30.0, 2.0 ** (attempt - 1))
                    print(f"  Fallo de red (intento {attempt}): {last_error}. Reintentando en {wait:.0f}s...", file=sys.stderr)
                    time.sleep(wait)
                    continue
                raise SystemExit(f"Error de red tras reintentos: {last_error}")
    finally:
        reader.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("python python_upload.py <archivo> <user_id>")
        print("")
        print("Ejemplo:")
        print("  python python_upload.py mi-archivo.zip 7970466590")
        sys.exit(1)
    file_path = sys.argv[1]
    user_id = int(sys.argv[2])


    def show(sent, total, speed):
        print(f"\r  {sent/total:.0%}  {speed:.2f} MB/s", end="", flush=True)


    url, seconds, etag = upload(file_path, user_id, progress=show)
    print(f"\n✅ Subido en {seconds:.1f}s")
    print(url)
    if etag:
        print(f"ETag: {etag}")
