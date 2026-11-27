import path from "node:path";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "/static/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  // O chunk do markdown (Streamdown + shiki) passa de 500 kB, mas só carrega sob demanda.
  build: { outDir: "../nickel/ui/static", emptyOutDir: true, chunkSizeWarningLimit: 600 },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/voice": "http://127.0.0.1:8000",
      "/auth": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
