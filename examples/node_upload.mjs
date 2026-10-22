import { argv, basename } from "node:path";
import { createReadStream } from "node:fs";
import { stat, readFile } from "node:fs/promises";
import path from "node:path";

const BASE = "https://s3.todus.cu/stream";
const CHUNK = 1024 * 1024; // 1 MB

function quoteName(name) {
  return name.split("").map(ch => encodeURIComponent(ch)).join("");
}

async function main() {
  const filePath = argv[2];
  const folder = argv[3] || "GRATIS/tg_prueba";
  if (!filePath) {
    console.error("node node_upload.mjs <archivo> [carpeta]");
    process.exit(1);
  }

  const { size } = await stat(filePath);
  const name = basename(filePath);
  const url = `${BASE}/${folder.replace(/\/+$/, "")}/${quoteName(name)}`;

  // PUT con streaming (Node 20+ fetch soporta bodies asíncronos, aquí usamos import claramente)
  const { Readable } = await import("node:stream");
  const { createReadStream } = await import("node:fs");

  let sent = 0;
  const fileStream = createReadStream(filePath, { highWaterMark: CHUNK });
  fileStream.on("data", (b) => (sent += b.length));

  const resp = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/octet-stream" },
    body: fileStream,
    duplex: "half",
  });

  if (![200, 201, 204].includes(resp.status)) {
    const text = await resp.text();
    console.error(`HTTP ${resp.status}: ${text.slice(0, 200)}`);
    process.exit(1);
  }
  console.log(`✅ Subido (${sent} bytes):`);
  console.log(url);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
