/** @type {import('eslint').Linter.Config[]} */
module.exports = [
  {
    ignores: ["dist/", "node_modules/", "release/", "dist-electron/", "*.js"],
  },
  {
    files: ["**/*.ts", "**/*.tsx"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      parser: require("@typescript-eslint/parser"),
      parserOptions: {
        ecmaVersion: 2022,
        sourceType: "module",
      },
    },
    plugins: {
      "@typescript-eslint": require("@typescript-eslint/eslint-plugin"),
      react: require("eslint-plugin-react"),
    },
    rules: {
      "react/react-in-jsx-scope": "off",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-explicit-any": "warn",
      // Renderer and shared code must not use console — all diagnostics
      // go through the typed IPC layer to the renderer's error display.
      "no-console": "error",
    },
    settings: {
      react: {
        version: "detect",
      },
    },
  },
  // Main process: console.log is used for backend diagnostics.
  // This is intentional — the main process logs to stderr for debugging
  // the Python backend lifecycle. The renderer must not use console.
  {
    files: ["src/main/**/*.ts"],
    rules: {
      "no-console": "off",
    },
  },
];
