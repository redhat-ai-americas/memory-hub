import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm"],
  dts: false,
  sourcemap: true,
  clean: true,
  target: "es2022",
  external: ["openclaw"],
  esbuildOptions(options) {
    options.loader = { ...options.loader, ".md": "text" };
  },
});
