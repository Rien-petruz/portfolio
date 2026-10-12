import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the engine API (default 127.0.0.1:8080).
const target = process.env.MIE_API ?? "http://127.0.0.1:8080";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target, ws: true },
      "/metrics": target,
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
