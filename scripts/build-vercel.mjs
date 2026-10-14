/**
 * Vercel build step for SiteSentinel.
 *
 * The scanner engine cannot run inside a Vercel Function (it needs a real
 * Chromium, the Lighthouse CLI, a writable artifact directory and a multi-minute
 * budget), so this repository deploys as:
 *
 *   • UI      -> Vercel (this static bundle)
 *   • engine  -> Cloud Run / any container host (see Dockerfile)
 *
 * This script points the UI at the engine. Set SCANNER_API_ORIGIN in the Vercel
 * project (Production + Preview) to the engine's public URL; when it is unset the
 * UI calls same-origin /api/*, which is what you want if you are serving the UI
 * from the engine itself.
 */

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const raw = (process.env.SCANNER_API_ORIGIN || "").trim().replace(/\/+$/, "");

if (raw && !/^https?:\/\//.test(raw)) {
  console.error(`✗ SCANNER_API_ORIGIN must start with http:// or https:// (got "${raw}")`);
  process.exit(1);
}

const body = `/* Generated at build time by scripts/build-vercel.mjs — do not edit by hand. */
window.SENTINEL_API = ${JSON.stringify(raw)};
`;

writeFileSync(join(root, "static", "app-config.js"), body, "utf8");
console.log(raw ? `✓ UI will call the engine at ${raw}` : "✓ UI will call same-origin /api/*");
