import { argv, basename } from "node:path";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import path from "node:path";

const BASE = "https://s3.todus.cu/stream";
const CHUNK = 1024 * 1024; // 1 MB

// FORMATO PERSISTENTE: users/df/<user_id>/  (ver README §2)
// El formato users/tg_<user_id>/ SE BORRA automáticamente por MinIO.
function folderForUser(userId) {
  return `users/df/${userId}`;
}

function quoteName(name) {
  return name.split("").map(ch => encodeURIComponent(ch)).join("");
}

async function main() {
  const filePath = argv[2];
  const userId = argv[3];
  if (!filePath || !userId) {
    console.error("node node_upload.mjs <archivo> <user_id>");
    console.error("");
    console.error("Ejemplo:");
    console.error("  node node_upload.mjs mi-archivo.zip 7970466590");
    process.exit(1);
  }

  const { size } = await stat(filePath);
  const name = basename(filePath);
  const folder = folderForUser(userId);
  const url = `${BASE}/${folder}/${quoteName(name)}`;

  console.log(`Subiendo a: ${url}`);

  const { Readable } = await import("node:stream");
  const fileStream = createReadStream(filePath, { highWaterMark: CHUNK });

  let sent = 0;
  fileStream.on("data", (b) => {
    sent += b.length;
    const pct = ((sent / size) * 100).toFixed(0);
    process.stdout.write(`\r  ${pct}%  ${(sent / 1024 / 1024).toFixed(1)} MB`);
  });

  const resp = await fetch(url, {
    method: "PUT",
    headers: {
      "Content-Type": "application/octet-stream",
      "Content-Length": String(size),
    },
    body: fileStream,
    duplex: "half",
  });

  if (![200, 201, 204].includes(resp.status)) {
    const text = await resp.text();
    console.error(`\nHTTP ${resp.status}: ${text.slice(0, 200)}`);
    process.exit(1);
  }

  const etag = resp.headers.get("etag");
  const rlRemaining = resp.headers.get("x-ratelimit-remaining");
  console.log(`\n✅ Subido (${sent} bytes)`);

  if (rlRemaining) {
    console.log(`Rate limit remaining: ${rlRemaining}`);
  }
  if (etag) {
    console.log(`ETag: ${etag}`);
  }

  // Verificar con HEAD que el archivo quedó persistido
  console.log("Verificando con HEAD...");
  await new Promise(r => setTimeout(r, 500));
  const headResp = await fetch(url, { method: "HEAD" });
  if (headResp.status !== 200) {
    console.error(`⚠️  HEAD devolvió ${headResp.status} — posible borrado por whitelist de prefijo`);
    process.exit(1);
  }
  console.log("✅ Archivo confirmado en S3:");
  console.log(url);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
