# -*- coding: utf-8 -*-
"""SDK Python para el bucket público de ToDus S3 (s3.todus.cu/stream).

Funcionalidades:
- upload(): subida con formato persistente users/df/<user_id>/ + reintentos
- download(): descarga con rangos (multi-hilo opcional)
- head(): comprobar existencia y metadatos
- delete(): borrar archivo
- list_bucket(): listar todo el bucket con paginación
- list_user(): listar archivos de un usuario específico
- list_prefix(): listar archivos bajo un prefijo arbitrario

Uso:
    from todus_sdk import ToDusS3
    s3 = ToDusS3()
    result = s3.upload("archivo.zip", user_id=7970466590, progress=print)
    print(result.url)
"""
from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable, Iterator, List, Optional
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)

# ─── Constantes ─────────────────────────────────────────────────────────
DEFAULT_BASE = "https://s3.todus.cu/stream"
DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MB
DEFAULT_TIMEOUT = 3600  # 1 hora para archivos grandes
DEFAULT_RETRIES = 3

# Whitelist de prefijos que persisten en el bucket (ver README §2)
# Cualquier otro prefijo es borrado por MinIO lifecycle rule.
PERSISTENT_PREFIXES = {"users", "hi", "dk"}


# ─── Excepciones ────────────────────────────────────────────────────────
class ToDusS3Error(Exception):
    """Error base del SDK."""


class UploadError(ToDusS3Error):
    """Fallo en la subida."""


class NotFoundError(ToDusS3Error):
    """El objeto no existe."""


class RateLimitError(ToDusS3Error):
    """Se agotó el rate limit (HTTP 429)."""


# ─── Tipos ──────────────────────────────────────────────────────────────
ProgressFn = Callable[[int, int, float], None]  # (done, total, speed_mbs)


@dataclass
class UploadResult:
    """Resultado de una subida."""
    url: str
    name: str
    size: int
    seconds: float
    speed_mbs: float
    etag: Optional[str] = None
    rate_limit_remaining: Optional[int] = None


@dataclass
class HeadInfo:
    """Información devuelta por HEAD."""
    exists: bool
    size: int
    etag: Optional[str]
    last_modified: Optional[str]
    content_type: Optional[str]
    accept_ranges: bool


@dataclass
class BucketEntry:
    """Entrada del listado del bucket."""
    key: str
    size: int
    last_modified: str
    etag: str

    @property
    def url(self) -> str:
        """URL pública del objeto."""
        encoded = "/".join(quote(p, safe="") for p in self.key.split("/"))
        return f"{DEFAULT_BASE}/{encoded}"

    @property
    def filename(self) -> str:
        """Nombre del archivo (último segmento del key)."""
        return self.key.rsplit("/", 1)[-1] if "/" in self.key else self.key


# ─── _ProgressReader ────────────────────────────────────────────────────
class _ProgressReader:
    """File-like que reporta progreso mientras requests lo lee."""

    def __init__(self, path: str, progress: Optional[ProgressFn] = None) -> None:
        self.f = open(path, "rb")
        self.total = os.path.getsize(path)
        self.progress = progress
        self.sent = 0
        self.t0 = time.time()
        self.last_report = 0.0

    def read(self, size: int = -1) -> bytes:
        chunk = self.f.read(size)
        if chunk and self.progress is not None:
            self.sent += len(chunk)
            now = time.time()
            if (now - self.last_report > 0.6) or (self.sent >= self.total):
                self.last_report = now
                elapsed = now - self.t0
                speed = (self.sent / elapsed / (1024 * 1024)) if elapsed > 0 else 0.0
                self.progress(self.sent, self.total, speed)
        return chunk

    def close(self) -> None:
        self.f.close()

    def rewind(self) -> None:
        self.f.seek(0)
        self.sent = 0
        self.t0 = time.time()
        self.last_report = 0.0


# ─── SDK principal ──────────────────────────────────────────────────────
class ToDusS3:
    """Cliente para el bucket público de ToDus S3."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.chunk_size = chunk_size
        self.timeout = timeout
        self.retries = max(1, retries)
        self.session = session or requests.Session()

    # ─── Construcción de URLs ───────────────────────────────────────────
    def build_url(self, folder: str, filename: str) -> str:
        """Construye la URL pública para `filename` dentro de `folder`."""
        safe_name = quote(filename, safe="")
        clean_folder = folder.strip("/")
        return f"{self.base}/{quote(clean_folder, safe='/')}/{safe_name}"

    def folder_for_user(self, user_id: int, prefix: str = "users") -> str:
        """Devuelve la carpeta S3 para un usuario.

        USA EL FORMATO PERSISTENTE: `<prefix>/df/<user_id>` si prefix='users'.
        El formato `<prefix>/tg_<user_id>` SE BORRA automáticamente (ver README §2).
        """
        if prefix == "users":
            return f"users/df/{user_id}"
        return f"{prefix}/tg_{user_id}"

    # ─── Upload ─────────────────────────────────────────────────────────
    def upload(
        self,
        path: str,
        user_id: Optional[int] = None,
        folder: Optional[str] = None,
        filename: Optional[str] = None,
        progress: Optional[ProgressFn] = None,
        retries: Optional[int] = None,
        verify: bool = True,
    ) -> UploadResult:
        """Sube un archivo al S3.

        Args:
            path: ruta local del archivo.
            user_id: ID numérico del usuario (si se pasa, se usa folder_for_user).
            folder: carpeta S3 completa (ignorado si se pasa user_id).
            filename: nombre del archivo en S3 (default: basename de path).
            progress: callback(done, total, speed_mbs).
            retries: número de reintentos (default: self.retries).
            verify: hacer HEAD después del PUT para confirmar.

        Returns:
            UploadResult con url, size, seconds, speed_mbs, etag.

        Raises:
            UploadError: si falla tras reintentos.
        """
        if not os.path.isfile(path):
            raise UploadError(f"El archivo no existe: {path}")

        if folder is None and user_id is not None:
            folder = self.folder_for_user(user_id)
        elif folder is None:
            raise UploadError("Debe pasar user_id o folder")

        size = os.path.getsize(path)
        name = filename or os.path.basename(path)
        url = self.build_url(folder, name)
        attempts = max(1, retries or self.retries)

        log.info("ToDus upload START → %s (%d bytes)", url, size)

        reader = _ProgressReader(path, progress)
        t0 = time.time()
        last_error: Optional[str] = None
        etag: Optional[str] = None
        rate_limit_remaining: Optional[int] = None

        try:
            for attempt in range(1, attempts + 1):
                reader.rewind()
                try:
                    resp = self.session.put(
                        url,
                        data=reader,
                        headers={
                            "Content-Length": str(size),
                            "Content-Type": "application/octet-stream",
                        },
                        timeout=self.timeout,
                    )

                    # Capturar etag y rate-limit de la respuesta
                    etag = resp.headers.get("ETag", etag)
                    rl = resp.headers.get("x-ratelimit-remaining")
                    if rl:
                        try:
                            rate_limit_remaining = int(rl)
                        except ValueError:
                            pass

                    # 5xx y 429 son transitorios → reintentar
                    if resp.status_code >= 500 or resp.status_code == 429:
                        last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                        if attempt < attempts:
                            wait = min(30.0, 2.0 ** (attempt - 1))
                            log.warning(
                                "ToDus upload falló (intento %d/%d: %s). Reintentando en %.0fs...",
                                attempt, attempts, last_error, wait,
                            )
                            time.sleep(wait)
                            continue
                        raise UploadError(
                            f"ToDus S3 rechazó la subida tras {attempts} intentos ({last_error})"
                        )

                    if resp.status_code not in (200, 201, 204):
                        raise UploadError(
                            f"ToDus S3 respondió HTTP {resp.status_code}: {resp.text[:200]}"
                        )

                    dt = max(0.001, time.time() - t0)
                    speed = (size / dt / (1024 * 1024)) if dt > 0 else 0.0
                    if progress is not None:
                        progress(size, size, speed)

                    # Verificar con HEAD si se solicitó
                    if verify:
                        time.sleep(0.5)  # dar tiempo a MinIO a persistir
                        head = self.head(url)
                        if not head.exists:
                            raise UploadError(
                                f"PUT devolvió 200 pero HEAD dice que no existe. "
                                f"Probablemente el prefijo '{folder.split('/')[0]}' "
                                f"no está en la whitelist (ver README §2)."
                            )

                    log.info(
                        "ToDus upload SUCCESS %s (%d bytes) en %.2fs (%.2f MB/s)",
                        name, size, dt, speed,
                    )
                    return UploadResult(
                        url=url, name=name, size=size, seconds=dt,
                        speed_mbs=speed, etag=etag,
                        rate_limit_remaining=rate_limit_remaining,
                    )

                except (requests.ConnectionError, requests.Timeout,
                        requests.ChunkedEncodingError, OSError) as net_err:
                    last_error = str(net_err)
                    if attempt < attempts:
                        wait = min(30.0, 2.0 ** (attempt - 1))
                        log.warning(
                            "ToDus upload fallo de red (intento %d/%d: %s). Reintentando en %.0fs...",
                            attempt, attempts, last_error, wait,
                        )
                        time.sleep(wait)
                        continue
                    raise UploadError(
                        f"Fallo de red subiendo a ToDus S3 tras {attempts} intentos: {last_error}"
                    ) from net_err
        finally:
            reader.close()

        raise UploadError(f"No se pudo subir el archivo: {last_error or 'error desconocido'}")

    # ─── Head ───────────────────────────────────────────────────────────
    def head(self, url: str) -> HeadInfo:
        """Comprueba existencia y metadatos del objeto."""
        try:
            resp = self.session.head(url, timeout=30)
            if resp.status_code == 200:
                return HeadInfo(
                    exists=True,
                    size=int(resp.headers.get("Content-Length", "0") or "0"),
                    etag=resp.headers.get("ETag"),
                    last_modified=resp.headers.get("Last-Modified"),
                    content_type=resp.headers.get("Content-Type"),
                    accept_ranges=resp.headers.get("Accept-Ranges") == "bytes",
                )
            return HeadInfo(
                exists=False, size=0, etag=None,
                last_modified=None, content_type=None, accept_ranges=False,
            )
        except requests.RequestException as e:
            raise ToDusS3Error(f"HEAD falló: {e}") from e

    # ─── Download ───────────────────────────────────────────────────────
    def download(
        self,
        url: str,
        output_path: str,
        progress: Optional[ProgressFn] = None,
        threads: int = 1,
    ) -> str:
        """Descarga un archivo del S3.

        Args:
            url: URL pública del objeto.
            output_path: ruta local donde guardar el archivo.
            progress: callback(done, total, speed_mbs).
            threads: número de hilos para descarga paralela (usa Range).
                     Si el servidor no soporta rangos, cae a 1 hilo.

        Returns:
            La ruta local del archivo descargado.
        """
        # Primero HEAD para saber tamaño y si soporta rangos
        info = self.head(url)
        if not info.exists:
            raise NotFoundError(f"El objeto no existe: {url}")

        if threads > 1 and info.accept_ranges and info.size > 0:
            return self._download_multithread(url, output_path, info.size, threads, progress)

        return self._download_single(url, output_path, info.size, progress)

    def _download_single(
        self,
        url: str,
        output_path: str,
        total_size: int,
        progress: Optional[ProgressFn],
    ) -> str:
        """Descarga en un solo hilo."""
        resp = self.session.get(url, stream=True, timeout=self.timeout)
        if resp.status_code != 200:
            raise ToDusS3Error(f"GET falló: HTTP {resp.status_code}")

        done = 0
        t0 = time.time()
        last_report = 0.0
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(self.chunk_size):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress is not None:
                    now = time.time()
                    if now - last_report > 0.6 or done >= total_size:
                        last_report = now
                        elapsed = now - t0
                        speed = (done / elapsed / (1024 * 1024)) if elapsed > 0 else 0.0
                        progress(done, total_size, speed)
        return output_path

    def _download_multithread(
        self,
        url: str,
        output_path: str,
        total_size: int,
        threads: int,
        progress: Optional[ProgressFn],
    ) -> str:
        """Descarga multi-hilo usando Range."""
        import concurrent.futures

        chunk_size = total_size // threads
        parts: List[str] = []

        def _download_chunk(idx: int, start: int, end: int) -> int:
            part_path = f"{output_path}.part{idx}"
            parts.append(part_path)
            headers = {"Range": f"bytes={start}-{end}"}
            resp = self.session.get(url, headers=headers, stream=True, timeout=self.timeout)
            if resp.status_code != 206:
                raise ToDusS3Error(f"Range request falló: HTTP {resp.status_code}")
            with open(part_path, "wb") as f:
                for chunk in resp.iter_content(self.chunk_size):
                    if chunk:
                        f.write(chunk)
            return os.path.getsize(part_path)

        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as exe:
            futures = []
            for i in range(threads):
                start = i * chunk_size
                end = (start + chunk_size - 1) if i < threads - 1 else total_size - 1
                futures.append(exe.submit(_download_chunk, i, start, end))
            done = 0
            for fut in concurrent.futures.as_completed(futures):
                done += fut.result()
                if progress is not None:
                    elapsed = max(0.001, time.time() - time.time())  # placeholder
                    progress(done, total_size, 0.0)

        # Unir partes
        with open(output_path, "wb") as out:
            for part in sorted(parts):
                with open(part, "rb") as p:
                    while True:
                        chunk = p.read(self.chunk_size)
                        if not chunk:
                            break
                        out.write(chunk)
                try:
                    os.unlink(part)
                except OSError:
                    pass

        return output_path

    # ─── Delete ─────────────────────────────────────────────────────────
    def delete(self, url: str) -> bool:
        """Borra un objeto. Devuelve True si el objeto ya no existe."""
        try:
            resp = self.session.delete(url, timeout=30)
            if resp.status_code in (200, 204, 404):
                return True
            log.warning("DELETE de %s respondió HTTP %d: %s",
                        url, resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as e:
            log.warning("No se pudo eliminar %s: %s", url, e)
            return False

    def delete_many(self, urls: List[str], batch_size: int = 25, delay: float = 0.3) -> tuple:
        """Borra una lista de URLs en lotes.

        Returns:
            (deleted_ok, failed) — listas de URLs.
        """
        deleted: List[str] = []
        failed: List[str] = []
        for i, url in enumerate(urls, 1):
            if self.delete(url):
                deleted.append(url)
            else:
                failed.append(url)
            if delay > 0:
                time.sleep(delay)
            if batch_size > 0 and i % batch_size == 0 and i < len(urls):
                log.info("Limpieza S3: pausa tras %d/%d", i, len(urls))
                time.sleep(2.0)
        return deleted, failed

    # ─── List ───────────────────────────────────────────────────────────
    def list_bucket(
        self,
        prefix: str = "",
        max_keys: int = 1000,
        max_pages: int = 100,
    ) -> Iterator[BucketEntry]:
        """Lista objetos del bucket con paginación.

        Args:
            prefix: filtra por prefijo (ej. "users/df/7970466590/").
            max_keys: claves por página.
            max_pages: máximo número de páginas a recorrer.

        Yields:
            BucketEntry por cada objeto.
        """
        continuation_token: Optional[str] = None
        ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

        for page in range(max_pages):
            params = {"list-type": "2", "max-keys": str(max_keys)}
            if prefix:
                params["prefix"] = prefix
            if continuation_token:
                params["continuation-token"] = continuation_token

            resp = self.session.get(self.base, params=params, timeout=60)
            if resp.status_code != 200:
                raise ToDusS3Error(f"List falló: HTTP {resp.status_code}: {resp.text[:300]}")

            root = ET.fromstring(resp.text)
            for contents in root.findall("s3:Contents", ns):
                key_el = contents.find("s3:Key", ns)
                size_el = contents.find("s3:Size", ns)
                lm_el = contents.find("s3:LastModified", ns)
                etag_el = contents.find("s3:ETag", ns)
                if key_el is None or size_el is None:
                    continue
                yield BucketEntry(
                    key=key_el.text or "",
                    size=int(size_el.text or "0"),
                    last_modified=(lm_el.text if lm_el is not None else ""),
                    etag=(etag_el.text or "").strip('"'),
                )

            truncated = root.find("s3:IsTruncated", ns)
            if truncated is None or truncated.text != "true":
                return

            nct = root.find("s3:NextContinuationToken", ns)
            if nct is None or not nct.text:
                return
            continuation_token = nct.text

    def list_user(self, user_id: int, prefix: str = "users") -> Iterator[BucketEntry]:
        """Lista todos los archivos de un usuario específico.

        Usa el formato persistente: <prefix>/df/<user_id>/
        """
        folder = self.folder_for_user(user_id, prefix)
        yield from self.list_bucket(prefix=f"{folder}/")

    def list_prefix(self, prefix: str) -> Iterator[BucketEntry]:
        """Lista archivos bajo un prefijo arbitrario."""
        yield from self.list_bucket(prefix=prefix)


# ─── CLI básico ─────────────────────────────────────────────────────────
def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="ToDus S3 SDK CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_up = sub.add_parser("upload", help="Subir archivo")
    p_up.add_argument("file")
    p_up.add_argument("--user-id", type=int, required=True)
    p_up.add_argument("--folder", help="(ignorado si se pasa --user-id)")
    p_up.add_argument("--name", help="nombre en S3 (default: basename)")

    p_dl = sub.add_parser("download", help="Descargar archivo")
    p_dl.add_argument("url")
    p_dl.add_argument("output")
    p_dl.add_argument("--threads", type=int, default=1)

    p_head = sub.add_parser("head", help="Verificar existencia")
    p_head.add_argument("url")

    p_del = sub.add_parser("delete", help="Borrar archivo")
    p_del.add_argument("url")

    p_list = sub.add_parser("list", help="Listar bucket")
    p_list.add_argument("--prefix", default="")
    p_list.add_argument("--user-id", type=int)
    p_list.add_argument("--max", type=int, default=1000)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    s3 = ToDusS3()

    if args.cmd == "upload":
        def prog(d, t, sp):
            print(f"\r  {d/t:.0%}  {sp:.2f} MB/s", end="", flush=True)
        r = s3.upload(args.file, user_id=args.user_id, folder=args.folder,
                      filename=args.name, progress=prog)
        print(f"\n✅ Subido en {r.seconds:.1f}s ({r.speed_mbs:.2f} MB/s)")
        print(r.url)
        if r.etag:
            print(f"ETag: {r.etag}")

    elif args.cmd == "download":
        def prog(d, t, sp):
            print(f"\r  {d/t:.0%}  {sp:.2f} MB/s", end="", flush=True)
        s3.download(args.url, args.output, progress=prog, threads=args.threads)
        print(f"\n✅ Descargado: {args.output}")

    elif args.cmd == "head":
        info = s3.head(args.url)
        if info.exists:
            print(f"✅ Existe ({info.size} bytes)")
            print(f"   ETag: {info.etag}")
            print(f"   Last-Modified: {info.last_modified}")
            print(f"   Accept-Ranges: {info.accept_ranges}")
        else:
            print("❌ No existe (404)")
            sys.exit(1)

    elif args.cmd == "delete":
        if s3.delete(args.url):
            print("✅ Borrado")
        else:
            print("❌ No se pudo borrar")
            sys.exit(1)

    elif args.cmd == "list":
        if args.user_id:
            entries = s3.list_user(args.user_id)
        else:
            entries = s3.list_prefix(args.prefix)
        count = 0
        total = 0
        for e in entries:
            if count >= args.max:
                break
            print(f"  {e.last_modified}  {e.size:>14}  {e.url}")
            count += 1
            total += e.size
        print(f"\nTotal: {count} archivos, {total/1024/1024:.2f} MB")


if __name__ == "__main__":
    import sys
    _cli()
