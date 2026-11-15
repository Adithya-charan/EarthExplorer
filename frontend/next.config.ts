import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Lets a second dev server run from the same folder (set NEXT_DIST_DIR=.next-alt) without Next's one-server lock.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  allowedDevOrigins: ["127.0.0.1"],
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    // Pin the workspace root to this folder. Without it Turbopack can pick up an unrelated
    // lockfile in a parent directory (e.g. the home folder) and warn about it.
    root: fileURLToPath(new URL(".", import.meta.url)),
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
