/// <reference types="vitest" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { devNull } from "node:os";

declare const process: { env: Record<string, string | undefined> };

export default defineConfig(({ mode }) => {
  const loadEnvFiles = process.env.COMPETISCOPE_LOAD_ENV_FILES === undefined
    || ["1", "true", "yes", "on"].includes(process.env.COMPETISCOPE_LOAD_ENV_FILES.trim().toLowerCase());
  const env = { ...(loadEnvFiles ? loadEnv(mode, fileURLToPath(new URL("..", import.meta.url)), "") : {}), ...process.env };
  return {
    // Vite 5 treats false as the project root; a character device has no env files.
    envDir: loadEnvFiles ? undefined : devNull,
    cacheDir: env.COMPETISCOPE_VITE_CACHE_DIR || undefined,
    plugins: [react()],
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            return id.indexOf("node_modules") >= 0 ? "vendor" : undefined;
          },
        },
      },
    },
    server: {
      port: Number(env.FRONTEND_PORT || 5173),
      strictPort: true,
      proxy: {
        "/api": {
          target: env.VITE_API_TARGET || `http://127.0.0.1:${env.BACKEND_PORT || 8000}`,
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: "./src/test/setup.ts",
    },
  };
});
