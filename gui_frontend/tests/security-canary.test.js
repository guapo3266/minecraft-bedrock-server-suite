// Canary de seguridad del frontend: ningún .js/.jsx de src/ puede inyectar
// HTML o ejecutar código dinámico (dangerouslySetInnerHTML / innerHTML / eval).
// Si alguien introduce uno de estos patrones, el test falla y obliga a
// revisión explícita antes de que llegue al dist/ que se sirve desde el repo.
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', 'src');

// Patrones construidos por concatenación: este archivo describe el canary y
// no debe auto-matchearse (aunque vive fuera de src/, es una defensa extra).
const FORBIDDEN = [
  { name: 'dangerously' + 'SetInnerHTML', re: /dangerously\s*SetInnerHTML/ },
  { name: 'inner' + 'HTML', re: /inner\s*HTML/ },
  { name: 'ev' + 'al(', re: /\bev\s*al\s*\(/ }
];

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });
}

const sourceFiles = walk(SRC_DIR).filter((f) => /\.(js|jsx)$/.test(f));

describe('canary de seguridad (inyección HTML / ejecución dinámica)', () => {
  it('hay archivos fuente que comprobar', () => {
    expect(sourceFiles.length).toBeGreaterThan(0);
  });

  for (const { name, re } of FORBIDDEN) {
    it(`ningún src/**/*.js|jsx contiene ${name}`, () => {
      const offenders = sourceFiles
        .filter((f) => re.test(readFileSync(f, 'utf8')))
        .map((f) => relative(SRC_DIR, f).replaceAll('\\', '/'));
      expect(offenders).toEqual([]);
    });
  }
});
