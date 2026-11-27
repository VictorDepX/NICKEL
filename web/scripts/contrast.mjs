// Contraste WCAG dos tokens de web/src/styles/globals.css (valores hex). Uso: node scripts/contrast.mjs
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../src/styles/globals.css", import.meta.url), "utf8");
const tok = Object.fromEntries([...css.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map((m) => [m[1], m[2]]));
const lum = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a, b) => {
  const [hi, lo] = [lum(tok[a]), lum(tok[b])].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
const pairs = [
  ["foreground", "background", 4.5],
  ["muted-foreground", "background", 4.5],
  ["subtle-foreground", "background", 4.5],
  ["primary-foreground", "primary", 4.5],
  ["ring", "background", 4.5],
  ["ring", "card", 4.5],
  ["sidebar-foreground", "sidebar", 4.5],
  ["muted-foreground", "sidebar", 4.5],
  ["subtle-foreground", "sidebar", 4.5],
  ["card-foreground", "card", 4.5],
  ["muted-foreground", "card", 4.5],
  ["subtle-foreground", "card", 4.5],
  ["destructive", "background", 4.5],
  ["destructive-foreground", "background", 4.5],
  ["destructive-foreground", "card", 4.5],
  ["warning-foreground", "card", 4.5],
  ["accent-foreground", "accent", 4.5],
  ["ring", "background", 3], // anel de foco x fundo
  ["ring", "card", 3],
  ["ring", "sidebar", 3],
];
let fail = 0;
for (const [fg, bg, min] of pairs) {
  const r = ratio(fg, bg);
  const ok = r >= min;
  if (!ok) fail++;
  console.log(`${ok ? "ok  " : "FAIL"} ${fg} em ${bg}: ${r.toFixed(2)} (min ${min})`);
}
process.exit(fail ? 1 : 0);
