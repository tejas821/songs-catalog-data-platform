import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { ChartModule } from 'primeng/chart';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { RatingModule } from 'primeng/rating';
import { TableLazyLoadEvent, TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { downloadCsv } from './csv';
import { COLUMNS, SearchResult, Song, SongPage } from './models';
import { SongsService } from './songs.service';

const PAGE_SIZE = 10;

@Component({
  selector: 'app-root',
  imports: [FormsModule, TableModule, ButtonModule, InputTextModule,
            RatingModule, TagModule, MessageModule, ChartModule],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  private api = inject(SongsService);

  readonly columns = COLUMNS;
  readonly pageSize = PAGE_SIZE;

  // --- table state -------------------------------------------------------
  songs = signal<Song[]>([]);
  total = signal(0);
  loading = signal(true);
  error = signal<string | null>(null);
  private sortBy = 'title';
  private order: 'asc' | 'desc' = 'asc';

  // --- search state ------------------------------------------------------
  query = '';
  search = signal<SearchResult | null>(null);

  // --- chart state -------------------------------------------------------
  scatterData = signal<any>(null);
  qualityData = signal<any>(null);
  missingNote = signal('');

  readonly scatterOptions = {
    responsive: true, maintainAspectRatio: false,
    scales: {
      x: { title: { display: true, text: 'Danceability' }, min: 0, max: 1 },
      y: { title: { display: true, text: 'Energy' }, min: 0, max: 1 },
    },
    plugins: {
      tooltip: { callbacks: { label: (c: any) => `${c.raw.title} (${c.raw.x}, ${c.raw.y})` } },
    },
  };
  readonly barOptions = {
    responsive: true, maintainAspectRatio: false, indexAxis: 'y' as const,
    plugins: { legend: { display: false } },
    scales: { x: { title: { display: true, text: 'Values the normalizer refused to trust' }, ticks: { precision: 0 } } },
  };

  constructor() {
    this.loadCharts();
  }

  /**
   * PrimeNG calls this on first render and on every page / sort change.
   * We forward it to the API, so sorting always covers the whole dataset --
   * never just the ten rows currently on screen.
   */
  onLazyLoad(event: TableLazyLoadEvent): void {
    const size = event.rows ?? PAGE_SIZE;
    const page = Math.floor((event.first ?? 0) / size) + 1;
    this.sortBy = (event.sortField as string) || 'title';
    this.order = event.sortOrder === -1 ? 'desc' : 'asc';

    this.loading.set(true);
    this.api.page(page, size, this.sortBy, this.order).subscribe({
      next: (result: SongPage) => {
        this.songs.set(result.items);
        this.total.set(result.total);
        this.error.set(null);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Could not reach the API on http://localhost:8000 — is the backend running?');
        this.loading.set(false);
      },
    });
  }

  onSearch(): void {
    if (!this.query.trim()) {
      this.search.set(null);
      return;
    }
    this.api.search(this.query).subscribe((result) => this.search.set(result));
  }

  clearSearch(): void {
    this.query = '';
    this.search.set(null);
  }

  /** Optimistic star rating: show it immediately, roll back if the API says no. */
  onRate(song: Song, stars: number | null | undefined): void {
    if (stars == null) return;
    const previous = song.rating;
    song.rating = stars;
    this.api.rate(song.id, stars).subscribe({
      error: () => {
        song.rating = previous;
        this.error.set(`Rating "${song.title}" failed.`);
      },
    });
  }

  exportPage(): void {
    downloadCsv(this.songs(), this.columns, `songs-page-${this.sortBy}-${this.order}.csv`);
  }

  exportAll(): void {
    this.api.all().subscribe((r) => downloadCsv(r.items, this.columns, 'songs-all.csv'));
  }

  // --- charts ------------------------------------------------------------

  /**
   * Two charts, both honest about the data rather than flattering to it:
   *   1. danceability vs energy, plotting only songs where BOTH are known;
   *   2. how many values per attribute the normalizer had to reject.
   */
  private loadCharts(): void {
    this.api.all().subscribe((result) => {
      const songs = result.items;

      const points = songs
        .filter((s) => s.danceability !== null && s.energy !== null)
        .map((s) => ({ x: s.danceability, y: s.energy, title: s.title }));
      this.scatterData.set({
        datasets: [{
          label: 'Songs', data: points,
          backgroundColor: '#4f7ff0', pointRadius: 6, pointHoverRadius: 8,
        }],
      });
      this.missingNote.set(
        `${points.length} of ${songs.length} songs plotted — ` +
        `${songs.length - points.length} are missing danceability or energy.`,
      );

      const fields = ['danceability', 'energy', 'mood', 'acousticness', 'tempo', 'valence', 'duration_ms'];
      const missing = fields.map((f) => songs.filter((s) => s[f as keyof Song] === null).length);
      this.qualityData.set({
        labels: fields,
        datasets: [{ data: missing, backgroundColor: '#e8a33d', borderRadius: 4 }],
      });
    });
  }

  // --- display helpers ---------------------------------------------------

  formatDuration(ms: number | null): string {
    if (ms === null) return '—';
    const seconds = Math.round(ms / 1000);
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  }

  cell(song: Song, field: keyof Song, kind?: string): string {
    const value = song[field];
    if (value === null || value === undefined) return '—';
    if (kind === 'duration') return this.formatDuration(value as number);
    if (kind === 'mood') return value === 1 ? 'Happy' : 'Sad';
    if (kind === 'ratio') return (value as number).toFixed(3);
    if (kind === 'tempo') return (value as number).toFixed(1);
    return String(value);
  }

  /** "duration_ms:seconds_converted(158s)" -> a short, readable chip. */
  flagLabel(flag: string): string {
    const [field, detail = ''] = flag.split(':');
    if (detail.startsWith('seconds_converted')) return `${field}: unit fixed`;
    if (detail.startsWith('out_of_range')) return `${field}: out of range`;
    if (detail.startsWith('implausible')) return `${field}: implausible`;
    if (detail === 'conflict') return `${field}: sources disagreed`;
    return `${field}: missing`;
  }

  flagSeverity(flag: string): 'warn' | 'danger' | 'info' {
    if (flag.includes('seconds_converted')) return 'info';
    if (flag.includes('conflict')) return 'warn';
    return 'danger';
  }
}
