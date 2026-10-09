/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8765" } },
  build: { outDir: "../src/rates_trainer/web/static", emptyOutDir: true, sourcemap: false },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"], css: false, include: ["src/**/*.test.{ts,tsx}"] },
});
