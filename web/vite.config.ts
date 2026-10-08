import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  build: {
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules")) {
            if (/three|react-three|drei/.test(id)) return "viewport";
            if (/recharts|d3-/.test(id)) return "charts";
            return "vendor";
          }
        },
      },
    },
  },
});
