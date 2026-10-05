import { defineConfig, globalIgnores } from "eslint/config";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

export default defineConfig([
  ...nextCoreWebVitals,
  {
    rules: {
      "@next/next/no-img-element": "off",
      // React Compiler rules that arrived with eslint-config-next 16. They
      // flag patterns that work today; warn until the code is cleaned up.
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/immutability": "warn",
      "react-hooks/purity": "warn",
    },
  },
  globalIgnores([".next/**", "node_modules/**", "next-env.d.ts", "scripts/**"]),
]);
