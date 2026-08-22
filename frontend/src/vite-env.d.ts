/// <reference types="vite/client" />

interface ImportMetaEnv {
  // 构建时经 vite.config.ts 的 define 注入，见 ADR-0030。
  readonly APP_VERSION: string;
}
