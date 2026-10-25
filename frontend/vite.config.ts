import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Override with NSS_BACKEND=http://host:port (e.g. to test the offline mock fallback).
const BACKEND = process.env.NSS_BACKEND || "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/ws": { target: BACKEND.replace("http", "ws"), ws: true, changeOrigin: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 1200,
  },
});
