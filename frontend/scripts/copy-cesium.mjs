// CesiumJS loads its web workers, imagery assets (NaturalEarthII, sky box, icons) and widget styles from a base URL.
// They are copied from node_modules to public/vendor/cesium so the globe works with no CDN and no access token.
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const from = join(root, "node_modules", "cesium", "Build", "Cesium");
const to = join(root, "public", "vendor", "cesium");
if (!existsSync(from)) {
  console.error(`copy-cesium: ${from} not found (run npm install)`);
  process.exit(1);
}
mkdirSync(to, { recursive: true });
for (const dir of ["Workers", "ThirdParty", "Assets", "Widgets"]) {
  cpSync(join(from, dir), join(to, dir), { recursive: true });
}
console.log("copy-cesium: copied Workers, ThirdParty, Assets and Widgets to public/vendor/cesium");
