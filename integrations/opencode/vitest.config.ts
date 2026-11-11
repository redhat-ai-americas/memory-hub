import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts", "../common/tests/**/*.test.ts"],
    environment: "node",
  },
});
