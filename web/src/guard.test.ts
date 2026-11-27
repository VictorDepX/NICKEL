import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "vitest";

const SRC = import.meta.dirname;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.(ts|tsx)$/.test(entry.name) && entry.name !== "guard.test.ts" ? [full] : [];
  });
}

test('nenhum arquivo importa de "cn" (o certo é "@/lib/utils")', () => {
  const offenders = sourceFiles(SRC).filter((file) => /from\s+["']cn["']/.test(readFileSync(file, "utf8")));
  expect(offenders.map((f) => path.relative(SRC, f))).toEqual([]);
});

test("package.json não depende do pacote npm `cn`", () => {
  const pkg = JSON.parse(readFileSync(path.join(SRC, "../package.json"), "utf8")) as Record<string, Record<string, string>>;
  expect({ ...pkg.dependencies, ...pkg.devDependencies }).not.toHaveProperty("cn");
});
