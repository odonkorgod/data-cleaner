import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development, requests to /api/* are forwarded to the FastAPI server,
// so the browser never makes a cross-origin request.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
