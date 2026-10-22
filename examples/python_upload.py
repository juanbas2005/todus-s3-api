# -*- coding: utf-8 -*-
"""Ejemplo de subida anónima a ToDus S3 con requests.

Uso: python python_upload.py <ruta_archivo> [carpeta]
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


def _progress_reader(progress=None):
    class ProgressReader:
        pass

    return None


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


def upload(path, folder, progress=None, retries=RETRIES, timeout=TIMEOUT):
    size = os.path.getsize(path)
    name = os.path.basename(path)
    safe_name = quote(name, safe="")
    url = f"{BASE}/{folder.strip('/')}/{safe_name}"
    session = requests.Session()
    reader = ProgressReader(path, progress)
    t0 = time.time()
    last_error = None
    try:
        for attempt in range(1, retries + 1):
            reader.rewind()
            try:
                resp = session.put(
                    url,
                    data=reader,
                    headers={"Content-Length": str(size), "Content-Type": "application/octet-stream"},
                    timeout=timeout,
                )
                if resp.status_code >= 500 or resp.status_code == 429:
                    last_error = f"HTTP {resp.status_code}"
                    if attempt < retries:
                        time.sleep(min(30.0, 2.0 ** (attempt - 1)))
                        continue
                    raise SystemExit(f"Fallo tras reintentos: {last_error}")
                if resp.status_code not in (200, 201, 204):
                    raise SystemExit(f"HTTP {resp.status_code}: {resp.text[:200]}")
                dt = max(0.001, time.time() - t0)
                if progress:
                    progress(size, size, size / dt / (1024 * 1024))
                return url, dt
            except (requests.ConnectionError, requests.Timeout) as err:
                last_error = str(err)
                if attempt < retries:
                    time.sleep(min(30.0, 2.0 ** (attempt - 1)))
                    continue
                raise SystemExit(f"Error de red tras reintentos: {last_error}")
    finally:
        reader.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("python python_upload.py <archivo> [carpeta]")
        sys.exit(1)
    file_path = sys.argv[1]
    folder = sys.argv[2] if len(sys.argv) > 2 else "GRATIS/tg_prueba"


    def show(sent, total, speed):
        print(f"\r  {sent/total:.0%}  {speed:.2f} MB/s", end="", flush=True)


    url, seconds = upload(file_path, folder, progress=show)
    print(f"\n✅ Subido en {seconds:.1f}s")
    print(url)
