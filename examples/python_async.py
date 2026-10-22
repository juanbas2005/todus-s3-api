# -*- coding: utf-8 -*-
"""Ejemplo asíncrono de subida a ToDus S3 con aiohttp.

Uso: python python_async.py <ruta_archivo> [carpeta]
"""
import asyncio
import os
import sys
from urllib.parse import quote

import aiohttp

BASE = "https://s3.todus.cu/stream"
CHUNK = 1024 * 1024  # 1 MB


async def upload(path, folder, progress=None, timeout=3600):
    size = os.path.getsize(path)
    name = os.path.basename(path)
    url = f"{BASE}/{folder.strip('/')}/{quote(name, safe='')}"

    async def gen():
        sent = 0
        with open(path, "rb") as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                sent += len(chunk)
                if progress:
                    progress(sent, size)
                yield chunk

    async with aiohttp.ClientSession() as session:
        async with session.put(url, data=gen(), headers={
            "Content-Length": str(size),
            "Content-Type": "application/octet-stream",
        }, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            status = resp.status
            if status not in (200, 201, 204):
                body = await resp.text()
                raise SystemExit(f"HTTP {status}: {body[:200]}")
            return url


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("python python_async.py <archivo> [carpeta]")
        sys.exit(1)
    file_path = sys.argv[1]
    folder = sys.argv[2] if len(sys.argv) > 2 else "GRATIS/tg_prueba"


    def show(sent, total):
        print(f"\r  {sent/total:.0%}  {sent/1024/1024:.1f} MB", end="", flush=True)


    url = asyncio.run(upload(file_path, folder, progress=show))
    print(f"\n✅ Subido: {url}")
