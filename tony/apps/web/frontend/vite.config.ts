/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The backend only accepts its own Origin, so the dev proxy rewrites the one of the
// Vite dev server (5173). Production serves the built files from the same origin.
const BACKEND = "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [react()],
  // Three.js sits alone in the orb's lazily loaded chunk (~590 kB, ~150 kB gzip).
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 650 },
  server: {
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true, headers: { Origin: BACKEND } },
      "/ws": { target: BACKEND, ws: true, changeOrigin: true, headers: { Origin: BACKEND } },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/setupTests.ts"],
    css: false,
  },
});
