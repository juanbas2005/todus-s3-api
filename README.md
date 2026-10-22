# ToDus S3 API — Documentación de la subida/borrado anónima

> **Actualizado y probado:** 2026-10-22 · endpoint `s3.todus.cu/stream` verificado con PUT/HEAD/GET.

Servidor MinIO anónimo de la plataforma cubana **ToDus** para almacenar y compartir archivos por HTTP. No se requiere autenticación explícita para subir (PUT), bajar (GET/HEAD) o borrar (DELETE).

---

## Índice

- [1. Base URL y formato de enlaces](#1-base-url-y-formato-de-enlaces)
- [2. Subir archivo — `PUT`](#2-subir-archivo--put)
- [3. Comprobar existencia — `HEAD`](#3-comprobar-existencia--head)
- [4. Descargar archivo — `GET`](#4-descargar-archivo--get)
- [5. Borrar archivo — `DELETE`](#5-borrar-archivo--delete)
- [6. Códigos de respuesta](#6-codigos-de-respuesta)
- [7. Limitaciones y notas](#7-limitaciones-y-notas)
- [8. Ejemplos en código](#8-ejemplos-en-codigo)
- [9. Referencia de la implementación original en el bot](#9-referencia-de-la-implementacion-original-en-el-bot)

---

## 1. Base URL y formato de enlaces

```
https://s3.todus.cu/stream/<carpeta>/<nombre>
```

| Concepto | Valor |
|---|---|
| **Base** | `https://s3.todus.cu/stream` |
| **Carpeta** | `GRATIS/tg_<user_id>` (ejemplo real usado en el bot) o cualquier jerarquía |
| **Nombre** | Nombre del archivo (se recomienda URL-encoding con `quote`) |
| **Formato final** | `https://s3.todus.cu/stream/<carpeta>/<nombre>` |

Ejemplo real verificado:

```
https://s3.todus.cu/stream/GRATIS/tg_99999/test-1792639105.txt
```

---

## 2. Subir archivo — `PUT`

Sube el contenido del cuerpo de la petición al objeto indicado por la URL.

### Memoria

```
PUT /stream/<carpeta>/<nombre> HTTP/2
Host: s3.todus.cu
```

| Cabecera | Valor | Obligatorio |
|---|---|---|
| `Content-Type` | `application/octet-stream` | No (por defecto) |
| `Content-Length` | Tamaño en bytes | Sí |

### curl

```bash
curl -X PUT \
     --data-binary @ruta/al/archivo \
     -H "Content-Type: application/octet-stream" \
     "https://s3.todus.cu/stream/GRATIS/tg_99999/mi-archivo.zip"
```

### Respuesta

```
HTTP/2 200
```

> Nota: es recomendable hacer un `HEAD` después del `PUT` para confirmar que el objeto quedó guardado (la política de persistencia la decide MinIO; en streaming algunas configuraciones responden antes de persistir).

---

## 3. Comprobar existencia — `HEAD`

Devuelve metadatos del objeto sin descargarlo.

```bash
curl -sSI "https://s3.todus.cu/stream/GRATIS/tg_99999/mi-archivo.zip"
```

```http
HTTP/2 200
accept-ranges: bytes
content-length: 22
content-type: application/octet-stream
etag: "80e8a2b622df0ef3ee9075b33a90d2c4"
last-modified: Thu, 22 Oct 2026 03:18:25 GMT
server: MinIO
```

- `200` → el objeto existe
- `404` → no existe

---

## 4. Descargar archivo — `GET`

Acceso de solo lectura al objeto.

```bash
curl -o archivo.bin "https://s3.todus.cu/stream/GRATIS/tg_99999/mi-archivo.zip"
```

Soporta rangos (`accept-ranges: bytes`), útil para descargas multi-hilo.

```bash
curl -H "Range: bytes=0-1023" "https://s3.todus.cu/stream/..." -o parte.bin
```

---

## 5. Borrar archivo — `DELETE`

MinIO acepta `DELETE` sin autenticación sobre la URL pública.

```bash
curl -X DELETE "https://s3.todus.cu/stream/GRATIS/tg_99999/mi-archivo.zip"
```

Éxito: `200`, `204` (borrado), `404` (ya no existía). Cualquier otro código = fallo.

---

## 6. Códigos de respuesta

| Código | Significado |
|---|---|
| `200` | OK (subida, descarga, delete) |
| `201` | Creado (equivalente a OK) |
| `204` | Sin contenido — borrado correcto |
| `400` | Petición mal formada |
| `404` | No existe el objeto |
| `429` | Límite de peticiones — transitorio, reintentar |
| `5xx` | Error de servidor — transitorio, reintentar |
| `307/308` | Redirección de MinIO en algunos endpoints (a veces) |

---

## 7. Limitaciones y notas

- **Tamaño:** no confirmado el límite oficial; el bot usa hasta 5 GB por archivo con streaming de 1 MB.
- **Sin auth:** dependen de que el bucket público lo permita. Puede cambiar sin aviso.
- **No hay MD5/checksum enviado:** los `etag` son calculados por MinIO. Para verificar integridad conviene calcular hash local y comparar.
- **El PUT es síncrono y bloqueante** para la lógica del bot (se ejecuta en un worker con semáforo).
- **Reintentos:** ante `5xx`/`429`/fallos de red, con backoff exponencial (1s, 2s, 4s... hasta 30s máximo, 3 intentos por defecto).
- **Dominio con certificado autofirmado** (cert self-signed) en algunos IPs: la app IroS3Dl fuerza SNI `s3.todus.cu`.
- **Velocidad:** depende de la conexión. El PUT anterior (22 bytes) fue trivial; para archivos grandes puede ir a varios MB/s.

---

## 8. Ejemplos en código

| Lenguaje | Archivo |
|---|---|
| Python (requests) | `examples/python_upload.py` |
| Python (asíncrono) | `examples/python_async.py` |
| JavaScript (Node) | `examples/node_upload.mjs` |
| curl (con reintentos) | `examples/curl_with_retry.sh` |

Ver [examples/README.md](examples/README.md) para más detalles.

---

## 9. Referencia de la implementación original en el bot

- Repo: `juanbas2005/S3` · módulo `bot/s3.py`
- Funciones: `build_url`, `folder_for_user`, `upload_to_s3`, `delete_from_s3`, `delete_many_from_s3`
- Config: `s3_base`, `s3_prefix`, `upload_retries`, `max_concurrent_jobs`

---

## Licencia

Documentación bajo MIT (ver `LICENSE`).
