# NovaSolver Studio — frontend

Vite + React + TypeScript + Tailwind CSS v4 + three.js. Fonts (Inter, Noto Sans JP/SC) are
bundled via @fontsource, so the app works offline.

## Run (development)

```powershell
cd studio\frontend
npm install          # first time only
npm run dev          # http://127.0.0.1:5173
```

The dev server proxies `/api` and `/ws` to the backend at `http://127.0.0.1:8765`
(override with `NSS_BACKEND=http://host:port`). If `GET /api/templates` fails at startup,
the app switches to a built-in demo backend (`src/api/mock.ts`, loaded lazily) and shows
"デモデータ / Demo data" in the status bar.

## Build

```powershell
npm run build        # tsc --noEmit + vite build -> dist/
npm run preview      # serve dist/ locally
```

## Layout of the source

```
src/
  api/        client.ts (HTTP + WS, ?lang=), types.ts, mock.ts (offline fallback only)
  state/      store.ts (app state, debounced PATCH with expected_revision, jobs, results)
  viewer/     framework-independent three.js viewer (DESIGN.md §7), colormaps
  components/ TopBar, Sidebar (steps + readiness), ViewerPane, ColorBar, PropertiesPanel,
              LogStrip, StatusBar, StartScreen, CommandPalette, AiPanel, ui/ (Button, Input,
              Select, Slider, Tabs, Tooltip, Dialog)
  i18n/       ja.json / en.json / zh.json (keys like step.mesh.title)
  lib/units.ts
```

Keyboard: `1`–`6` steps, `F` fit view, `Esc` clear selection, `Ctrl/⌘+K` command palette.
