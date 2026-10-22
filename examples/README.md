# Ejemplos

Scripts listos para probar la subida anónima a ToDus S3.

| Archivo | Lenguaje | Descripción |
|---|---|---|
| `curl_with_retry.sh` | bash / curl | PUT con reintentos y verificación `HEAD` posterior |
| `python_upload.py` | Python + requests | PUT con streaming, progreso y reintentos |
| `python_async.py` | Python + aiohttp | PUT asíncrono con generador de chunks |
| `node_upload.mjs` | Node 20+ (fetch nativo) | PUT con stream y cabeceras |

## Uso rápido

```bash
# curl
./curl_with_retry.sh /mi/archivo.zip GRATIS/tg_prueba

# python síncrono
python python_upload.py /mi/archivo.zip GRATIS/tg_prueba

# python asíncrono
python python_async.py /mi/archivo.zip GRATIS/tg_prueba

# node
node node_upload.mjs /mi/archivo.zip GRATIS/tg_prueba
```

Todas las carpetas se crean implícitamente al subir (MinIO anónimo).
