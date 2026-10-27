# Ejemplos de uso de la API de ToDus S3

## Tabla de ejemplos

| Archivo | Lenguaje | Descripción |
|---|---|---|
| [`todus_sdk.py`](./todus_sdk.py) | Python | **SDK completo** — upload/download/head/delete/list con formato persistente y reintentos |
| [`python_upload.py`](./python_upload.py) | Python | Subida con requests + verificación HEAD |
| [`python_async.py`](./python_async.py) | Python | Subida asíncrona con aiohttp |
| [`python_download.py`](./python_download.py) | Python | Descarga simple/multi-hilo con Range + verificación ETag |
| [`python_list_bucket.py`](./python_list_bucket.py) | Python | Listar bucket completo con paginación (text/urls/csv/json) |
| [`python_dktodus_backend.py`](./python_dktodus_backend.py) | Python | Cliente del backend DK ToDus (auth, uploads, stats, devices) |
| [`node_upload.mjs`](./node_upload.mjs) | JavaScript | Subida con Node.js fetch + streams |
| [`curl_with_retry.sh`](./curl_with_retry.sh) | Bash | Shell script robusto con reintentos |

---

## ⚠️ Importante: formato persistente

Todos los ejemplos usan el formato `users/df/<user_id>/` que **persiste** en el bucket.
El formato `users/tg_<user_id>/` (legacy) **se borra automáticamente** por MinIO.

Ver [README §2](../README.md#2--whitelist-de-prefijos-y-formato-persistente) para más detalles.

---

## Instalación

### Python

```bash
pip install requests aiohttp
```

### Node.js

```bash
# Node 20+ tiene fetch nativo, no necesita dependencias
node examples/node_upload.mjs archivo.zip 7970466590
```

---

## Uso rápido

### SDK Python (recomendado)

```python
import sys
sys.path.insert(0, "examples")
from todus_sdk import ToDusS3

s3 = ToDusS3()

# Subir
result = s3.upload("mi-archivo.zip", user_id=7970466590)
print(result.url)

# Listar archivos de un usuario
for entry in s3.list_user(7970466590):
    print(entry.url, entry.size)

# Descargar
s3.download(result.url, "descarga.zip")

# Borrar
s3.delete(result.url)
```

### CLI del SDK

```bash
# Subir
python examples/todus_sdk.py upload mi-archivo.zip --user-id 7970466590

# Descargar
python examples/todus_sdk.py download https://s3.todus.cu/stream/users/df/7970466590/archivo.zip salida.zip

# Listar bucket
python examples/todus_sdk.py list --user-id 7970466590

# HEAD
python examples/todus_sdk.py head https://s3.todus.cu/stream/users/df/7970466590/archivo.zip

# Borrar
python examples/todus_sdk.py delete https://s3.todus.cu/stream/users/df/7970466590/archivo.zip
```

### Subida simple

```bash
# Python
python examples/python_upload.py mi-archivo.zip 7970466590

# Asíncrono
python examples/python_async.py mi-archivo.zip 7970466590

# Node.js
node examples/node_upload.mjs mi-archivo.zip 7970466590

# Bash
./examples/curl_with_retry.sh mi-archivo.zip 7970466590
```

### Listar bucket completo

```bash
# Texto (default)
python examples/python_list_bucket.py

# Solo URLs
python examples/python_list_bucket.py --format urls

# CSV
python examples/python_list_bucket.py --format csv > archivos.csv

# JSON
python examples/python_list_bucket.py --format json > archivos.json

# Filtrar por prefijo (solo archivos de un usuario)
python examples/python_list_bucket.py --prefix "users/df/7970466590/"

# Filtrar por tamaño mínimo (1 MB)
python examples/python_list_bucket.py --min-size 1048576
```

### Descargar

```bash
# Descarga simple
python examples/python_download.py https://s3.todus.cu/stream/users/df/7970466590/archivo.zip salida.zip

# Multi-hilo (4 hilos con Range)
python examples/python_download.py https://s3.todus.cu/stream/users/df/7970466590/archivo.zip salida.zip --threads 4
```

### Backend DK ToDus

```bash
# Estadísticas globales (sin auth)
python examples/python_dktodus_backend.py stats

# Obtener temp_token
python examples/python_dktodus_backend.py init

# Obtener JWT (acepta cualquier telegram_id)
python examples/python_dktodus_backend.py verify <temp_token> 7970466590 --username test

# Ver perfil
python examples/python_dktodus_backend.py me <jwt>

# Listar subidas propias
python examples/python_dktodus_backend.py uploads <jwt> --limit 100

# Registrar dispositivo
python examples/python_dktodus_backend.py register-device "mi_device_id_12345678" --platform android

# Estado de un dispositivo
python examples/python_dktodus_backend.py device-status "mi_device_id_12345678"
```

---

## Características del SDK

| Feature | Soportado |
|---|---|
| Subida con formato persistente | ✅ |
| Reintentos con backoff exponencial | ✅ |
| Verificación HEAD post-subida | ✅ |
| Descarga simple | ✅ |
| Descarga multi-hilo (Range) | ✅ |
| Listado del bucket con paginación | ✅ |
| Filtrado por prefijo | ✅ |
| Borrado individual y por lotes | ✅ |
| Callback de progreso | ✅ |
| Rate-limit tracking | ✅ |
| ETag tracking | ✅ |
| Soporte asíncrono (aiohttp) | ✅ |
| CLI integrado | ✅ |

---

## Verificación post-subida

**Crítico:** Tras cada subida, hacer un HEAD para confirmar que el archivo persistió. Si el HEAD devuelve 404, el prefijo no está en la whitelist y MinIO borró el archivo.

```python
result = s3.upload("archivo.zip", user_id=7970466590, verify=True)
# verify=True (default) hace HEAD automáticamente y lanza UploadError si falla
```
