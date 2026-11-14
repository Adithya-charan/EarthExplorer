import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Without this Vite 8 fails to resolve bare packages from files rewritten by vi.mock when the checkout sits under OneDrive.
    preserveSymlinks: true,
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.tsx"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
    testTimeout: 15000,
    restoreMocks: true,
  },
});
