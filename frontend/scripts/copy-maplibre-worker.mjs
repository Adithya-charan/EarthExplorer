// MapLibre GL v6 loads its web worker from a URL. Bundlers cannot resolve that URL reliably, so the worker files
// are copied from node_modules to public/vendor/maplibre and the map is pointed at them (see MapCanvas.tsx).
import { copyFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const from = join(root, "node_modules", "maplibre-gl", "dist");
const to = join(root, "public", "vendor", "maplibre");
mkdirSync(to, { recursive: true });
for (const f of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
  const src = join(from, f);
  if (!existsSync(src)) {
    console.error(`copy-maplibre-worker: ${src} not found (is maplibre-gl installed?)`);
    process.exit(1);
  }
  copyFileSync(src, join(to, f));
}
console.log("copy-maplibre-worker: copied worker files to public/vendor/maplibre");
