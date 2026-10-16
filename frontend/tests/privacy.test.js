/**
 * Guards the privacy rule at the source level: a student-facing component must
 * never read a numeric score, a score breakdown or an admin-confirmed input,
 * because the backend does not send one.
 *
 * The AI suggestion (`ai_*`) is different: the 201 body of POST
 * /api/complaints now carries it for the reporter, so ResultPanel may render
 * it. Scores and confirmed inputs stay admin-only, always.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(process.cwd(), 'src');

function read(relative) {
  return readFileSync(join(SRC, relative), 'utf8');
}

const STUDENT_VIEWS = [
  'pages/MyComplaintsPage.jsx',
  'components/ResultPanel.jsx',
  'pages/CommunityPage.jsx',
];

const FORBIDDEN = [
  'priority_score',
  'score_breakdown',
  'confirmed_urgency',
  'confirmed_impact',
  'confirmed_safety',
  'confirmed_by',
  'student_id',
];

describe('student and public views never read internal fields', () => {
  STUDENT_VIEWS.forEach((file) => {
    it(`${file} contains no internal field name`, () => {
      const src = read(file);
      FORBIDDEN.forEach((field) => {
        expect(src, `${file} must not reference ${field}`).not.toContain(field);
      });
    });
  });
});

describe('secrets are never referenced in frontend source', () => {
  it('no source file mentions the service role key', () => {
    const offenders = [];
    const walk = (dir) => {
      readdirSync(dir).forEach((name) => {
        const full = join(dir, name);
        if (statSync(full).isDirectory()) {
          walk(full);
          return;
        }
        if (!/\.(js|jsx|css|html)$/.test(name)) return;
        const src = readFileSync(full, 'utf8');
        // Strip comments first: a file may legitimately WARN against using the
        // service role key in the browser. Only real code counts as an offender.
        const code = src
          .replace(/\/\*[\s\S]*?\*\//g, '')
          .replace(/(^|[^:])\/\/.*$/gm, '$1');
        if (code.includes('service_role') || code.includes('SERVICE_ROLE')) {
          offenders.push(name);
        }
      });
    };
    walk(SRC);
    expect(offenders).toEqual([]);
  });

  it('.env.example exposes only VITE_ public variables', () => {
    const env = readFileSync(join(process.cwd(), '.env.example'), 'utf8');
    const keys = env
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith('#'))
      .map((line) => line.split('=')[0]);
    keys.forEach((key) => expect(key).toMatch(/^VITE_/));
  });
});
