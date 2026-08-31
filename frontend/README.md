# Frontend

Angular 22 + PrimeNG dashboard for the songs API. See the [repo README](../README.md)
for how to run everything; in short: start the backend on port 8000, then
`npm install && npm start` here.

- `src/app/models.ts` — the `Song` shape and the table's column definitions
- `src/app/songs.service.ts` — HTTP calls; the API owns sorting and paging
- `src/app/csv.ts` — CSV export (RFC-4180 quoting, UTF-8 BOM for Excel)
- `src/app/app.ts` / `app.html` — the dashboard
- `src/app/*.spec.ts` — 8 vitest tests (`npm test`)
