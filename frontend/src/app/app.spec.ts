import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import { App } from './app';
import { Song } from './models';

const EMPTY_PAGE = { page: 1, size: 200, total: 0, total_pages: 1, sort_by: 'title', order: 'asc', items: [] };

function song(overrides: Partial<Song> = {}): Song {
  return {
    index: 0, id: 'x', title: 't', title_key: 't',
    danceability: 0.5, energy: 0.5, mood: 1, acousticness: 0.5,
    tempo: 120, valence: null, duration_ms: 225947,
    num_sections: 8, num_segments: 800,
    flags: [], sources: ['part1'], rating: null, ...overrides,
  };
}

describe('App', () => {
  let http: HttpTestingController;
  let app: App;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    app = TestBed.createComponent(App).componentInstance;
    http = TestBed.inject(HttpTestingController);
    http.expectOne((r) => r.url.endsWith('/songs')).flush(EMPTY_PAGE);   // charts request
  });

  it('turns the table\'s 0-based offset into a 1-based API page', () => {
    app.onLazyLoad({ first: 20, rows: 10, sortField: 'tempo', sortOrder: -1 });
    const request = http.expectOne((r) => r.url.endsWith('/songs') && r.params.get('page') === '3');
    expect(request.request.params.get('sort_by')).toBe('tempo');
    expect(request.request.params.get('order')).toBe('desc');
    request.flush({ ...EMPTY_PAGE, items: [song()], total: 25 });
    expect(app.total()).toBe(25);
  });

  it('shows an unknown value as a dash instead of zero', () => {
    expect(app.cell(song({ tempo: null }), 'tempo', 'tempo')).toBe('—');
    expect(app.cell(song({ tempo: 108.73 }), 'tempo', 'tempo')).toBe('108.7');
  });

  it('formats duration from milliseconds', () => {
    expect(app.cell(song(), 'duration_ms', 'duration')).toBe('3:46');
  });

  it('rolls the star rating back when the API rejects it', () => {
    const target = song({ rating: 2 });
    app.onRate(target, 5);
    expect(target.rating).toBe(5);                                   // optimistic
    http.expectOne((r) => r.url.includes('/rating')).flush(null, { status: 404, statusText: 'Not Found' });
    expect(target.rating).toBe(2);                                   // rolled back
  });

  it('turns a raw normalizer flag into a readable chip', () => {
    expect(app.flagLabel('duration_ms:seconds_converted(158s)')).toBe('duration_ms: unit fixed');
    expect(app.flagLabel('danceability:conflict')).toBe('danceability: sources disagreed');
    expect(app.flagSeverity('acousticness:out_of_range(-0.05)')).toBe('danger');
  });
});
