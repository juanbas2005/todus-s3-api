# -*- coding: utf-8 -*-
"""Lista TODO el bucket público de ToDus S3 con paginación.

El bucket es totalmente público: cualquiera puede listar todos los archivos
con la API S3 estándar (list-type=2). Ver README §7.

Uso: python python_list_bucket.py [--prefix PREFIX] [--max-keys N] [--max-pages N]
"""
import argparse
import sys
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

BASE = "https://s3.todus.cu/stream"
NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


def list_bucket(prefix="", max_keys=1000, max_pages=100):
    """Itera sobre todos los objetos del bucket (o bajo un prefijo).

    Yields:
        dict con keys: key, size, last_modified, etag, url
    """
    session = requests.Session()
    continuation_token = None

    for page in range(max_pages):
        params = {"list-type": "2", "max-keys": str(max_keys)}
        if prefix:
            params["prefix"] = prefix
        if continuation_token:
            params["continuation-token"] = continuation_token

        resp = session.get(BASE, params=params, timeout=60)
        if resp.status_code != 200:
            print(f"Error HTTP {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
            return

        root = ET.fromstring(resp.text)

        for contents in root.findall("s3:Contents", NS):
            key_el = contents.find("s3:Key", NS)
            size_el = contents.find("s3:Size", NS)
            lm_el = contents.find("s3:LastModified", NS)
            etag_el = contents.find("s3:ETag", NS)
            if key_el is None or size_el is None:
                continue
            key = key_el.text or ""
            encoded = "/".join(quote(p, safe="") for p in key.split("/"))
            yield {
                "key": key,
                "size": int(size_el.text or "0"),
                "last_modified": lm_el.text if lm_el is not None else "",
                "etag": (etag_el.text or "").strip('"') if etag_el is not None else "",
                "url": f"{BASE}/{encoded}",
            }

        truncated = root.find("s3:IsTruncated", NS)
        if truncated is None or truncated.text != "true":
            return

        nct = root.find("s3:NextContinuationToken", NS)
        if nct is None or not nct.text:
            return
        continuation_token = nct.text


def main():
    p = argparse.ArgumentParser(description="Listar bucket público de ToDus S3")
    p.add_argument("--prefix", default="",
                   help="filtra por prefijo (ej. 'users/df/7970466590/' o 'users/')")
    p.add_argument("--max-keys", type=int, default=1000,
                   help="claves por página (default 1000)")
    p.add_argument("--max-pages", type=int, default=100,
                   help="máximo número de páginas (default 100)")
    p.add_argument("--format", choices=["text", "urls", "json", "csv"], default="text",
                   help="formato de salida")
    p.add_argument("--min-size", type=int, default=0,
                   help="tamaño mínimo en bytes (default 0)")
    args = p.parse_args()

    count = 0
    total_size = 0

    if args.format == "csv":
        print("last_modified,size_bytes,key,url")
    elif args.format == "json":
        print("[")

    first = True
    for entry in list_bucket(args.prefix, args.max_keys, args.max_pages):
        if entry["size"] < args.min_size:
            continue
        count += 1
        total_size += entry["size"]

        if args.format == "text":
            size_mb = entry["size"] / 1024 / 1024
            print(f"{entry['last_modified']}  {size_mb:>10.2f} MB  {entry['url']}")
        elif args.format == "urls":
            print(entry["url"])
        elif args.format == "csv":
            print(f"{entry['last_modified']},{entry['size']},{entry['key']},{entry['url']}")
        elif args.format == "json":
            if not first:
                print(",")
            import json
            print("  " + json.dumps(entry, ensure_ascii=False), end="")
            first = False

    if args.format == "json":
        print("\n]")

    print(f"\n--- Total: {count} archivos, {total_size/1024/1024:.2f} MB ---",
          file=sys.stderr)


if __name__ == "__main__":
    main()
