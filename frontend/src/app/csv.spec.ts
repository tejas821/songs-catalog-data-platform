import { describe, expect, it, vi } from 'vitest';

import { downloadCsv } from './csv';
import { COLUMNS, Song } from './models';

function song(overrides: Partial<Song>): Song {
  return {
    index: 0, id: 'x', title: 't', title_key: 't',
    danceability: null, energy: null, mood: null, acousticness: null,
    tempo: null, valence: null, duration_ms: null,
    num_sections: null, num_segments: null,
    flags: [], sources: ['part1'], rating: null, ...overrides,
  };
}

/** Capture the CSV text instead of actually downloading it. */
function capture(rows: Song[]): string {
  let captured = '';
  vi.stubGlobal('Blob', class { constructor(parts: string[]) { captured = parts.join(''); } });
  vi.stubGlobal('URL', { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  downloadCsv(rows, COLUMNS, 'test.csv');
  vi.unstubAllGlobals();
  return captured;
}

describe('downloadCsv', () => {
  it('quotes titles that contain a comma or a quote', () => {
    const csv = capture([song({ title: 'Hello, "World"' })]);
    expect(csv).toContain('"Hello, ""World"""');
  });

  it('writes unknown values as empty cells rather than the string "null"', () => {
    const csv = capture([song({ tempo: null, energy: 0.5 })]);
    expect(csv).not.toContain('null');
    expect(csv).toContain('"0.5"');
  });

  it('flattens flags into one readable column', () => {
    const csv = capture([song({ flags: ['tempo:implausible(0.0)', 'energy:missing'] })]);
    expect(csv).toContain('"tempo:implausible(0.0) | energy:missing"');
  });
});
