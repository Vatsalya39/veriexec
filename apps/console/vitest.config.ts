import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // Fixtures served at /golden/* in the app come from the repo's contracts dir.
      "@contracts": fileURLToPath(new URL("../../contracts", import.meta.url)),
    },
  },
  server: {
    fs: { allow: [fileURLToPath(new URL("../..", import.meta.url))] },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
    // jsdom only provisions localStorage when the document has a real origin; the default
    // `about:blank` leaves it undefined and every storage-reading test dies on `.clear()`.
    environmentOptions: {
      jsdom: { url: "http://localhost:5173/" },
    },
  },
});

