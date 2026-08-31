import { Column, Song } from './models';

/** RFC-4180 quoting: wrap in quotes and double any quote inside. */
function cell(value: unknown): string {
  const text = value === null || value === undefined ? '' : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

/** Build a CSV from the given rows and trigger a browser download. */
export function downloadCsv(rows: Song[], columns: Column[], filename: string): void {
  const header = ['id', ...columns.map((c) => c.header), 'rating', 'flags'];
  const lines = rows.map((row) =>
    [row.id, ...columns.map((c) => row[c.field]), row.rating, row.flags.join(' | ')].map(cell).join(','),
  );
  const csv = [header.map(cell).join(','), ...lines].join('\r\n');

  // ﻿ (BOM) so Excel opens the UTF-8 titles ("Café del Mar") correctly.
  const url = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' }));
  const link = Object.assign(document.createElement('a'), { href: url, download: filename });
  link.click();
  URL.revokeObjectURL(url);
}
