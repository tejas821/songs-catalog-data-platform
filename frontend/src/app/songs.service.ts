import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { SearchResult, Song, SongPage } from './models';

const API = 'http://localhost:8000/api';

/** Thin wrapper over the API. No caching, no state -- the components own that. */
@Injectable({ providedIn: 'root' })
export class SongsService {
  private http = inject(HttpClient);

  /** Sorting is applied by the server across the whole dataset, then paged. */
  page(page: number, size: number, sortBy: string, order: 'asc' | 'desc'): Observable<SongPage> {
    return this.http.get<SongPage>(`${API}/songs`, {
      params: { page, size, sort_by: sortBy, order },
    });
  }

  /** Everything in one call -- used by the charts and the "export all" button. */
  all(): Observable<SongPage> {
    return this.page(1, 200, 'title', 'asc');
  }

  search(title: string): Observable<SearchResult> {
    return this.http.get<SearchResult>(`${API}/songs/search`, { params: { title } });
  }

  rate(id: string, stars: number): Observable<Song> {
    return this.http.put<Song>(`${API}/songs/${id}/rating`, { stars });
  }
}
