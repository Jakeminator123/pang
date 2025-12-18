import tseslint from "@typescript-eslint/eslint-plugin";
import tsparser from "@typescript-eslint/parser";
import nextPlugin from "@next/eslint-plugin-next";

const nextCoreWebVitals = nextPlugin.configs["core-web-vitals"];

/** @type {import('eslint').Linter.Config[]} */
export default [
  {
    ignores: [".next/**", "node_modules/**", "out/**", "*.config.*"],
  },
  {
    files: ["**/*.{js,jsx,ts,tsx}"],
    name: nextCoreWebVitals.name,
    languageOptions: {
      parser: tsparser,
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
    },
    plugins: {
      ...nextCoreWebVitals.plugins,
      "@typescript-eslint": tseslint,
    },
    rules: {
      ...nextCoreWebVitals.rules,
      "@typescript-eslint/no-unused-vars": "warn",
      "no-console": "off",
    },
  },
];

