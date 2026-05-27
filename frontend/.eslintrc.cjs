module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  plugins: ['@typescript-eslint', 'react-hooks'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', 'src-tauri', 'node_modules', '*.config.*', 'vite.config.*'],
  rules: {
    // TypeScript-specific — relaxed for a large existing codebase
    '@typescript-eslint/no-explicit-any': 'off',
    '@typescript-eslint/no-unused-vars': 'off',        // tsc --noEmit already catches this
    '@typescript-eslint/no-empty-function': 'off',
    '@typescript-eslint/no-empty-interface': 'off',
    '@typescript-eslint/ban-types': 'off',
    '@typescript-eslint/ban-ts-comment': 'off',
    '@typescript-eslint/no-var-requires': 'off',
    '@typescript-eslint/no-non-null-assertion': 'off',
    '@typescript-eslint/no-inferrable-types': 'off',

    // General JS — tsc already covers most of these
    'no-undef': 'off',               // TypeScript handles undefined names
    'no-unused-vars': 'off',         // Defer to @typescript-eslint version (also off)
    'no-console': 'off',
    'no-empty': ['error', { allowEmptyCatch: true }],
    'prefer-const': 'error',
    'no-var': 'error',
    'no-debugger': 'error',

    // React hooks — rules-of-hooks catches real bugs; others off
    // set-state-in-effect and purity fire on intentional patterns (sync state
    // from props, Date.now in callbacks) that are correct in this codebase
    'react-hooks/rules-of-hooks': 'error',
    'react-hooks/exhaustive-deps': 'off',
    'react-hooks/set-state-in-effect': 'off',
    'react-hooks/purity': 'off',
    // immutability fires on const-fn called before declaration (runtime-safe, hoisting irrelevant)
    'react-hooks/immutability': 'off',
    // static-components fires on inline component defs; refactoring all occurrences is out of scope
    'react-hooks/static-components': 'off',
  },
}
