/** One row of the normalized table, exactly as the API returns it. */
export interface Song {
  index: number;
  id: string;
  title: string;
  title_key: string;
  danceability: number | null;
  energy: number | null;
  mood: number | null;
  acousticness: number | null;
  tempo: number | null;
  valence: number | null;
  duration_ms: number | null;
  num_sections: number | null;
  num_segments: number | null;
  /** Why a value is null, or what the normalizer had to correct. */
  flags: string[];
  /** Which export(s) this song came from. */
  sources: string[];
  rating: number | null;
}

export interface SongPage {
  page: number;
  size: number;
  total: number;
  total_pages: number;
  sort_by: string;
  order: 'asc' | 'desc';
  items: Song[];
}

export interface SearchResult {
  query: string;
  match_type: 'exact' | 'partial' | 'none' | 'empty_query';
  count: number;
  matches: Song[];
}

/** Column definition: `field` must be a sortable field on the API side. */
export interface Column {
  field: keyof Song;
  header: string;
  /** How to render the cell; everything else is printed as-is. */
  kind?: 'ratio' | 'duration' | 'mood' | 'tempo';
}

export const COLUMNS: Column[] = [
  { field: 'title', header: 'Title' },
  { field: 'danceability', header: 'Danceability', kind: 'ratio' },
  { field: 'energy', header: 'Energy', kind: 'ratio' },
  { field: 'mood', header: 'Mood', kind: 'mood' },
  { field: 'acousticness', header: 'Acousticness', kind: 'ratio' },
  { field: 'tempo', header: 'Tempo (BPM)', kind: 'tempo' },
  { field: 'valence', header: 'Valence', kind: 'ratio' },
  { field: 'duration_ms', header: 'Duration', kind: 'duration' },
  { field: 'num_sections', header: 'Sections' },
  { field: 'num_segments', header: 'Segments' },
];
