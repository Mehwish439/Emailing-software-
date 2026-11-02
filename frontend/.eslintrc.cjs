module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  parserOptions: { ecmaVersion: "latest", sourceType: "module", ecmaFeatures: { jsx: true } },
  extends: ["eslint:recommended", "plugin:react/recommended", "plugin:react-hooks/recommended"],
  settings: { react: { version: "18.3" } },
  rules: { "react/prop-types": "off", "react/react-in-jsx-scope": "off", "react/no-unescaped-entities": "off" },
};
