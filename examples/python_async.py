# -*- coding: utf-8 -*-
"""Ejemplo asíncrono de subida a ToDus S3 con aiohttp.

USO DEL FORMATO PERSISTENTE: users/df/<user_id>/  (ver README §2)

Uso: python python_async.py <ruta_archivo> <user_id>
"""
import asyncio
import os
import sys
import time
from urllib.parse import quote

import aiohttp

BASE = "https://s3.todus.cu/stream"
CHUNK = 1024 * 1024  # 1 MB


def folder_for_user(user_id):
    """FORMATO PERSISTENTE: users/df/<user_id>/"""
    return f"users/df/{user_id}"


async def upload(path, user_id, progress=None, timeout=3600, verify=True):
    """Sube un archivo bajo users/df/<user_id>/.

    Args:
        path: ruta local del archivo
        user_id: ID numérico del usuario
        progress: callback(done, total)
        timeout: timeout en segundos
        verify: hacer HEAD después del PUT para confirmar

    Returns:
        url del archivo subido
    """
    size = os.path.getsize(path)
    name = os.path.basename(path)
    folder = folder_for_user(user_id)
    url = f"{BASE}/{folder}/{quote(name, safe='')}"

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
            etag = resp.headers.get("ETag")
            rl_remaining = resp.headers.get("x-ratelimit-remaining")
            if rl_remaining:
                print(f"  Rate limit remaining: {rl_remaining}", file=sys.stderr)
            if status not in (200, 201, 204):
                body = await resp.text()
                raise SystemExit(f"HTTP {status}: {body[:200]}")

        # Verificar con HEAD
        if verify:
            await asyncio.sleep(0.5)
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=30)) as head_resp:
                if head_resp.status != 200:
                    raise SystemExit(
                        f"PUT OK pero HEAD dice {head_resp.status}. "
                        f"Posible borrado por whitelist de prefijo."
                    )

        return url, etag


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("python python_async.py <archivo> <user_id>")
        print("")
        print("Ejemplo:")
        print("  python python_async.py mi-archivo.zip 7970466590")
        sys.exit(1)
    file_path = sys.argv[1]
    user_id = int(sys.argv[2])


    def show(sent, total):
        print(f"\r  {sent/total:.0%}  {sent/1024/1024:.1f} MB", end="", flush=True)


    url, etag = asyncio.run(upload(file_path, user_id, progress=show))
    print(f"\n✅ Subido: {url}")
    if etag:
        print(f"ETag: {etag}")
