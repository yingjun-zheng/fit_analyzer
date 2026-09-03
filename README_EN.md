# 🚴 Cycling FIT Data Analyzer (Fit Analyzer)

A free, local, offline **cycling FIT data analysis tool** (pure desktop Windows app, native PySide6 GUI, no browser, no local server). Inspired by the analysis features of Garmin Connect / XOSS.

- **Native desktop GUI** with **batch import** of `.fit` files exported from bike computers (iGPSPORT / Garmin / XOSS and other major devices), stored in local SQLite
- Per-activity display: **record time, average speed, calories, max speed, average heart rate, average cadence, total ascent** and 16+ metrics
- **Per-kilometer speed line chart**, **speed zone stats**, **heart rate stats & zones**, **cadence stats & zones**, **altitude stats**, **device temperature stats**
- **Lap (segment) data detail**, **all activity detail fields**
- **Track map**: optional AMap online map, or fixed background image + track overlay (start/end markers, altitude range)
- **Monthly summary**: rides per month / distance / time / ascent / calories, with cross-month line charts
- **Training load trend**: monthly view shows CTL (fitness) / ATL (fatigue) / TSB (form) as three curves, computed with daily calendar-day decay over all data
- **Route analysis**: one-click convert a historical activity to a route, GPX route import, climb-segment highlighting on the elevation profile (Cat4~HC five levels), AI route difficulty interpretation
- **Route planning**: interactive point selection on AMap (XOSS style), waypoint chaining, GCJ-02 → WGS-84 coordinate correction
- **Auto route planning**: describe your needs in one sentence (e.g. "Beijing to Tianjin, rest every 35 km, where there is supply"), AI parsing + segmented relay + nearby rest-point marking — ideal for long-distance / cross-city rides
- **Heart-rate zone deep summary**: turn 5-zone HR distribution into training-structure diagnosis (aerobic / threshold / anaerobic proportions + pace comparison + advice)
- **Nutrition plan**: quantified hydration / carbohydrate / electrolyte recommendations by distance / time / intensity / temperature
- **FTP auto-estimation**: best 20-minute power × 0.95 to estimate FTP + power-to-weight ratio
- **Ride safety analysis**: heuristic detection of sudden stops / suspected crashes (sharp speed drop + prolonged stillness)
- **3D route view**: grade-colored 3D route (green→yellow→red) + altitude curtain, shown in route analysis
- **AI data analysis**: connect to a local AI (Ollama / LM Studio / vLLM) or any OpenAI-compatible remote model (DeepSeek etc., with your own key) to generate per-activity analysis reports and monthly training summaries
- **GPX export**: export a single activity as GPX 1.1 (with Garmin TrackPointExtension: HR / cadence / temperature / speed / power), compatible with Strava / Garmin Connect / XOSS
- Built-in **logging system** (rolling files + in-app live view)

---

## 1. Running

### Packaged EXE (recommended)
Double-click `dist\骑行FIT数据分析器\骑行FIT数据分析器.exe` to run (no console window; close the window to exit).

### From source
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

## 2. Usage

1. Open the app → toolbar "**Batch import FIT files**", select multiple `.fit` files (up to hundreds at once; re-importing auto-updates without duplicates).
2. Training records are listed by month on the left. Click a month for the **monthly summary** (count / distance / time / ascent / calories + cross-month charts + activity list; double-click an activity for detail).
3. Click a single activity for detail (tabs):
   - **Overview**: 16+ metric cards + per-km average speed chart + full speed/HR/cadence/altitude curves + device temperature curve
   - **Zone stats**: speed zones, HR zones (Z1~Z5 by % of max HR), cadence zones (time-weighted) + proportion text
   - **Laps**: per-lap start time / duration / distance / avg speed / max speed / HR / cadence / calories / ascent / descent
   - **Track**: track overlay on a fixed background image (start/end markers, altitude range)
   - **Activity detail**: all fields (device, sport type, file, import time, etc.)
   - **AI analysis**: click "Generate AI analysis report"

## 3. AI integration (optional, free)

Settings → AI:

| Scenario | URL | Notes |
| --- | --- | --- |
| Ollama (local) | `http://127.0.0.1:11434/v1` | use `ollama list` to find pulled models; enter the exact model name (e.g. `qwen3.5-4b:latest`) |
| LM Studio (local) | `http://127.0.0.1:1234/v1` | load any GGUF |
| DeepSeek / OpenAI | `https://api.deepseek.com/v1` | enter your own key |

> A wrong model name triggers a 404 and **automatically lists the models available on the server** for easy correction.

Once enabled:
- Single activity → "Generate AI analysis report": overall assessment, intensity/rhythm analysis (HR zones / speed distribution), problems and training advice
- Monthly view → "AI monthly summary": training volume, intensity structure, consistency, next-month advice
- Activity detail → "Smart review" (top of the AI analysis tab): triggered by one sentence, auto-routed to 6 analysis types

All AI calls go through your configured endpoint. The app does not include any paid interface; the key is stored locally and masked.

## Smart review agent (conversational, one-line trigger)

There is a unified review entry at the top of the "AI analysis" tab, plus a CLI:

```bash
python -m core.review_cli "review last week for me"
python -m core.review_cli "did I improve compared to last time"
python -m core.review_cli "should I rest this week"
python -m core.review_cli "has my fitness improved"
```

Auto-routed to 6 analysis types:

| Intent | Trigger example | What it does |
| --- | --- | --- |
| Single review | how was this ride | reuses the existing tool-calling agent (8 tools) |
| Period review | review last week / this month | monthly aggregation (6 tools) |
| Comparison review | did I improve vs last time | same-route identification + per-item diff + coach comments |
| Training load | should I rest this week | TSS/CTL/ATL/TSB (auto uses HR-based hrTSS when no power meter) |
| Fitness analysis | has my fitness improved | heart-rate/speed ratio, aerobic decoupling, HR zones, cadence quality |

Technical notes: intent classification first passes a keyword rule (fast, zero cost); only falls back to the LLM if no match. Single/period reviews reuse the existing ReAct agent; without an LLM the pure computation layers (comparison / load / fitness) still produce structured data standalone.

> When using a reasoning model (DeepSeek-R1 / o-series), empty or timed-out replies usually mean the model spent all tokens on the reasoning chain — the code passes `reasoning_effort=low` to work around it, so no manual intervention is needed in most cases.

## Route analysis (climb classification + AI interpretation)

Toolbar "🔁 Convert to route" turns the currently selected historical activity into a route, or use the "Route" entry next to "📤 Export GPX" to import a GPX route file. The route dialog provides:

- **Elevation profile**: altitude curve along distance, with climb segments highlighted in color bands (Cat4 → HC, five levels by gradient/length)
- **Climb list**: identifies continuous climb segments with category, length, average gradient, accumulated ascent
- **AI interpretation**: calls the LLM for difficulty rating, climb comments, supply advice
- **Export**: export the route as GPX for use on other platforms

> GPX with missing altitude (coordinates only) gets altitude auto-filled online (Open-Meteo) for climb analysis; silently degrades when offline.

## Route planning (interactive AMap point selection)

Toolbar "🧭 Route planning" opens the map-interactive route planner (XOSS-style):

1. **Click to add waypoints** on the AMap on the left (with numbered markers); the right-side list syncs in real time
2. Waypoints are planned by AMap cycling routing (segmented planning + splicing), avoiding "rocket straight lines" between start and end, keeping to actual ridable roads
3. Click "Plan route" to generate and render on the map; click "Convert to route analysis" to reuse the route dialog (altitude / climb / AI / export)

**Dependency**: fill in an AMap "**Web service**" key under Settings → AMap route planning (a different key type from the track page's "Web JS API" key). Personal certification offers tens of thousands of free calls per month — plenty for personal use.

> Coordinate correction: AMap returns GCJ-02 (Mars coordinates); the app uniformly converts to WGS-84 for storage and export, avoiding 300–500 m drift in exported routes.

## Auto route planning (long-distance / cross-city)

Toolbar "✨ Auto route planning" generates a long-distance route from a one-line description:

1. **Natural-language input**: e.g. "From Beijing to Tianjin via national roads, rest every 35 km, where there is supply"
   - AI parses it into parameters (origin / destination / segment length / rest-point type); if AI is not configured or parsing fails, a form fallback lets you fill manually
2. **Segmented relay**: split the long route into segments by "segment length" (your stamina threshold), each segment planned via AMap cycling routing and spliced together
3. **Nearby rest-point marking**: at each segment junction, use AMap POI search to find supply/rest points (convenience store / supermarket / restaurant / gas station / lodging / pharmacy) attached to the route

> Ideal for long-distance, cross-city, cross-province rides — for short rides use "🧭 Route planning" manual point selection; long rides are too tedious to mark manually and AMap has limited support for very long distances.

## 4. Statistics methodology

- **HR zones**: 5 zones by % of max HR (default 60/70/80/90%); max HR is taken from data or manually overridden; activities without HR data auto-hide HR analysis
- **Speed zones / cadence zones**: thresholds adjustable under Settings → Zone stats (speed default 10–35 km/h in 5 km/h steps; cadence default 60–100 rpm in 10 rpm steps)
- **Zone durations**: accumulated by per-record time weight
- **Altitude/temperature/HR/cadence curves**: auto downsampled (≤600 points); track downsampled to ≤2000 points

## 5. Track map

The "Track" page supports two modes, auto-switched:

1. **AMap online map (recommended, optional)**: after filling in the "**Web (JS API)**" key and security key you applied for at the [AMap open platform](https://lbs.amap.com/), the track is overlaid on a real map (custom start/end markers, front-end WGS-84→GCJ-02 correction to fit roads).
   - How to apply: AMap open platform → Console → App management → Create app → Add key; make sure the service platform is "**Web (JS API)**", and generate/view the **security key (securityJsCode)** in Settings.
   - The key is stored in plaintext locally and written into the embedded page, only for local rendering; it is recommended to set a **domain whitelist** in the console (leave empty for desktop sources).
   - **Dependency**: requires `PySide6` WebEngine components (`PySide6-Addons` / full `PySide6`). The WebEngine bundle is large — make sure the build script includes the QtWebEngine resources.
2. **Fixed background image (default)**: when no key is configured, or the environment lacks WebEngine, it auto-falls back — a random image from `backgrounds\` is used as the background, and the track scales to the GPS bounding box. A small note at the bottom says "AMap key not configured" or "WebEngine component missing".
   - To change/add backgrounds: place images (jpg/jpeg/png) into the `backgrounds\` folder (source version) and repackage; if the directory is missing it falls back to `back9.jpeg` at the root.
- The track is an approximate line of per-second location points; the page shows "no track" when there is no GPS data.

## 6. Data & logs

- Data directory: `%APPDATA%\FitAnalyzer\`
  - `fit.db` SQLite database (activities / laps / per-record points)
  - `logs\fit_analyzer.log` rolling log (2 MB × 5 files)
- Toolbar "Logs" for live view (auto-refresh); "Data directory" opens the data folder.
- CLI args: `--data-dir` (custom data dir), `--debug` (verbose logging), `--selftest` (offscreen self-test).

## 7. Repackaging the EXE

**Recommended: one-click script** (auto-clean → package → produce the final exe):

```powershell
.\.venv\Scripts\python.exe build\pack.py
```

Alternative: original PowerShell script

```powershell
powershell -ExecutionPolicy Bypass -File build\build_exe.ps1        # directory build
powershell -ExecutionPolicy Bypass -File build\build_exe.ps1 -OneFile
```

> The build environment needs `PySide6` (with WebEngine, full or `PySide6-Addons`) + `pyinstaller` + `pillow` + `fitparse`.
> **WebEngine is explicitly included via `build\fit_analyzer.spec`'s `hiddenimports`** (`QtWebEngineWidgets`/`QtWebEngineCore`/`QtWebChannel`); the output is about 500MB+ which is normal (includes `QtWebEngineProcess.exe`, `resources.pak`, `qtwebengine_locales`).
> After a directory build, run `骑行FIT数据分析器.exe --selftest` for an offscreen self-test to confirm WebEngine/main program work.

## 8. Project structure

```
fit_analyzer/
├── app.py                # entry (PySide6; includes --selftest offscreen self-test)
├── gui/
│   ├── main_window.py    # main window: month-activity tree / monthly summary / activity detail tabs
│   ├── charts.py         # QtCharts wrappers (line/bar/zone/multi-line/climb bands)
│   ├── track_widget.py   # track widget (fixed background image + track)
│   ├── amap_track.py     # TrackMapPanel: AMap online map / image background auto-switch
│   ├── route_dialog.py   # route analysis dialog (elevation + climb + AI + export)
│   ├── route_plan_map.py # route planning dialog (AMap interactive selection, QWebEngineView)
│   ├── auto_plan_dialog.py # auto route planning dialog (natural language + form fallback)
│   ├── route_3d.py       # 3D route view (grade-colored route)
│   ├── dialogs.py        # settings / logs dialogs
│   └── theme.py          # styles & formatting
├── core/
│   ├── fit_parser.py     # FIT parsing (fitparse; tolerant to missing fields/HR, local timezone)
│   ├── db.py             # SQLite storage & monthly summary
│   ├── analysis.py       # per-km / zone / curve / track stats
│   ├── route.py          # route: coords → distance / elevation profile / climb / altitude fill
│   ├── route_ai.py       # route AI interpretation
│   ├── route_plan.py     # route planning: AMap cycling routing / waypoints / GCJ-02→WGS-84
│   ├── route_ai_plan.py  # auto planning: LLM parsing of natural-language requirements
│   ├── route_long_plan.py # auto planning: segmented relay + POI rest-point marking
│   ├── training_load.py  # training load: TSS/CTL/ATL/TSB (HR-based hrTSS when no power meter)
│   ├── hr_summary.py     # HR zone deep summary (training structure diagnosis)
│   ├── nutrition.py      # nutrition plan
│   ├── ftp_estimate.py   # FTP auto-estimation
│   ├── safety.py         # ride safety analysis (sudden-stop / crash detection)
│   ├── gpx_export.py     # GPX 1.1 export (HR/cadence/temperature/speed/power extensions)
│   ├── ai_client.py      # OpenAI-compatible client (with missing-model hint)
│   ├── ai_analysis.py    # activity/monthly AI analysis prompts
│   ├── month_agent.py    # monthly ride query agent (tool-calling)
│   ├── review_agent.py   # smart review agent (intent routing)
│   └── config.py / logging_setup.py / http_utils.py
├── back9.jpeg            # track background image
├── build/                # PyInstaller spec + pack.py + build_exe.ps1
└── tests/                # smoke tests / route / route-planning unit tests
```

## 9. Known limitations

- For data **absent** from the FIT file (e.g. some bike computers do not record HR/power), the UI shows "—"; other stats are unaffected.
- The track is an approximate line of per-second location points; some devices sample at 10-second intervals, making the track look polyline-like.
- Only cycling FIT is supported; other sport types are parsed as records anyway (the sport field is preserved as-is).

### Garmin course files

A **course file** exported from the Garmin Connect website/app (usually `COURSE_xxx.fit`, `file_id.type = course`) is a different kind of data from an **activity file** (`type = activity`) recorded by the bike computer:

| | Activity file (bike computer) | Course file (Connect export) |
|------|------|------|
| Device model | ✅ present (`garmin_product` is a specific product code, e.g. Edge series) | ❌ absent |
| Max speed | ✅ present (`max_speed` / `enhanced_max_speed`) | ❌ absent |
| Content | full ride record (speed/HR/cadence/power etc.) | route track coordinates + total distance/ascent only |

### Bike computers tested so far (welcome to provide data from other brands for testing)
- IGP BSC200
- IGP BSC300
- IGP BiNavi
- Bryton Rider 15 (product code 1801, mapped to Rider 15; override in "Settings → Device model table" if it is actually another model)
- Magene C606 Pro
- Garmin
