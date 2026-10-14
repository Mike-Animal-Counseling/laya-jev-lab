# TypeScript compiler and API compatibility

`npm run typecheck` runs TypeScript 7 explicitly. The `typescript-7` npm alias keeps the new compiler independent of tools that require the JavaScript compiler API. ESLint and other API consumers resolve the supported TypeScript 6 package. Both are locked and validated; no peer dependency checks are bypassed.

Do not replace the API package with TypeScript 7 until its consumers support that API. Update both compiler paths through the existing CI checks. CI configuration, diagnostics authored by this project, and contribution standards use English.
