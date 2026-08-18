import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backendOrigin = env.VITE_BACKEND_ORIGIN || "http://127.0.0.1:8080";

  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        "/api": backendOrigin,
        "/health": backendOrigin,
      },
    },
  };
});
