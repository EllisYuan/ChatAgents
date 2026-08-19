import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backendOrigin = env.VITE_BACKEND_ORIGIN || "http://127.0.0.1:8080";
  // 版本号只由 git tag 决定（ADR-0030）：构建时经 APP_VERSION 环境变量注入，
  // 未设时取 "dev"，与后端 /health 的默认值保持一致。
  const appVersion = process.env.APP_VERSION || "dev";

  return {
    plugins: [react(), tailwindcss()],
    define: {
      "import.meta.env.APP_VERSION": JSON.stringify(appVersion),
    },
    server: {
      proxy: {
        "/api": backendOrigin,
        "/health": backendOrigin,
      },
    },
  };
});
