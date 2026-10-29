# UK Wind Generation

A small React + FastAPI app that shows actual UK wind generation and the day-ahead forecast for a selected day in January 2026.

## What it shows

Choose a delivery date to request the backend data. The page displays all 48 half-hour settlement periods with actual generation (`generation`), forecast generation, and their difference in MW. Missing source values are shown as `—`.

The backend fetches actual wind from Elexon BMRS `FUELHH/stream` and forecasts from `WINDFOR/stream`. It selects the latest forecast published by 09:30 UTC on the day before delivery. Forecasts are hourly, so a forecast is reused for the corresponding `:30` settlement period.

There is no application cache: each date selection makes fresh requests to Elexon.

## Run locally

Start the backend:

```sh
cd backend
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

In another terminal:

```sh
cd frontend
npm install
npm run dev
```

The Vite development server proxies API requests to `http://localhost:8000`. Set `VITE_API_BASE_URL` when the API is hosted elsewhere.

## Build frontend

```sh
cd frontend
npm run build
```

## AI-tool disclosure

AI tools were used to assist in building this application.
