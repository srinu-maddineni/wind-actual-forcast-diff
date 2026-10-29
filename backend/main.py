import json
import math
import statistics
import time
import urllib.error
import urllib.request
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Initialize FastAPI application
app = FastAPI(
    title="UK Wind Generation API",
    description="Half-hourly actual wind generation and day-ahead forecast metrics.",
    version="1.0.0",
)

# Enable CORS for React frontend (localhost:5173, localhost:3000, or any origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def fetch_json(url: str, retries: int = 3) -> list | dict:
    """Fetch JSON data from Elexon BMRS API with automatic retries."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "FastAPI-WindApp/1.0", "Accept": "application/json"},
    )
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                    return data["data"]
                return data
        except urllib.error.HTTPError as err:
            last_err = err
            if err.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(1 * (attempt + 1))
                continue
            raise HTTPException(status_code=502, detail=f"Elexon API HTTP {err.code}: {err.reason}") from err
        except urllib.error.URLError as err:
            last_err = err
            if attempt < retries - 1:
                time.sleep(1 * (attempt + 1))
                continue
            raise HTTPException(status_code=502, detail=f"Elexon API connection error: {err.reason}") from err
        except Exception as err:
            raise HTTPException(status_code=500, detail=f"Error reading Elexon response: {str(err)}") from err

    raise HTTPException(status_code=502, detail=f"Elexon API failed after retries: {last_err}")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/wind-data")
def get_wind_data(target_date: str = "2026-01-15") -> dict:
    parts = target_date.split("-")
    
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format for '{target_date}'. Expected YYYY-MM-DD.",
        )

    # Simple cutoff: if target is Jan 1, fetch Dec 31
    if target_date == "2026-01-01":
        cutoff_str = "2025-12-31T09:30:00Z"
        publish_from_str = "2025-12-29T09:30:00Z"
    elif target_date == "2026-01-02":
        cutoff_str = "2026-01-01T09:30:00Z"
        publish_from_str = "2025-12-30T09:30:00Z"
    else:
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        cutoff_str = f"{year:04d}-{month:02d}-{day - 1:02d}T09:30:00Z"
        publish_from_str = f"{year:04d}-{month:02d}-{day - 3:02d}T09:30:00Z"

    # 1. Fetch FUELHH (Actual generation)
    fuelhh_url = (
        f"https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH/stream"
        f"?settlementDateFrom={target_date}&settlementDateTo={target_date}&fuelType=WIND"
    )
    fuelhh_raw = fetch_json(fuelhh_url)
    fuelhh_rows = fuelhh_raw if isinstance(fuelhh_raw, list) else []

    # Filter rows where fuelType == "WIND" and startTime starts with target_date
    actual_rows = [
        r
        for r in fuelhh_rows
        if r.get("fuelType") == "WIND" and str(r.get("startTime", "")).startswith(target_date)
    ]
    actual_rows.sort(key=lambda r: str(r.get("startTime", "")))

    actual_by_start = {
        r.get("startTime"): r for r in actual_rows if r.get("startTime")
    }

    # 2. Fetch WINDFOR (Forecasts)
    windfor_url = (
        f"https://data.elexon.co.uk/bmrs/api/v1/datasets/WINDFOR/stream"
        f"?publishDateTimeFrom={publish_from_str}&publishDateTimeTo={cutoff_str}"
    )
    windfor_raw = fetch_json(windfor_url)
    windfor_rows = windfor_raw if isinstance(windfor_raw, list) else []

    # Filter WINDFOR rows where publishTime <= cutoff
    valid_forecasts = [
        r for r in windfor_rows if str(r.get("publishTime", "")) <= cutoff_str
    ]

    forecasts_by_start: dict[str, list[dict]] = {}
    for r in valid_forecasts:
        st = r.get("startTime")
        if st:
            forecasts_by_start.setdefault(st, []).append(r)

    # 3. Match 48 half-hour slots chronologically (00:00 to 23:30)
    timeseries: list[dict] = []
    for period in range(1, 49):
        hour = (period - 1) // 2
        minute = 30 if (period - 1) % 2 == 1 else 0
        slot_start_iso = f"{target_date}T{hour:02d}:{minute:02d}:00Z"

        actual_row = actual_by_start.get(slot_start_iso)
        actual_val = actual_row.get("generation") if actual_row else None
        actual_mw = float(actual_val) if actual_val is not None else None

        # Match by startTime (if no exact :30 forecast row, pair with :00 hourly forecast)
        candidates = forecasts_by_start.get(slot_start_iso, [])
        if not candidates and ":30:" in slot_start_iso:
            hourly_key = slot_start_iso.replace(":30:", ":00:")
            candidates = forecasts_by_start.get(hourly_key, [])

        if candidates:
            best_fc = max(candidates, key=lambda r: str(r.get("publishTime", "")))
            fc_val = best_fc.get("generation")
            forecast_mw = float(fc_val) if fc_val is not None else None
            pub_time = best_fc.get("publishTime")
        else:
            forecast_mw = None
            pub_time = None

        err_mw = (
            (forecast_mw - actual_mw)
            if (forecast_mw is not None and actual_mw is not None)
            else None
        )

        timeseries.append(
            {
                "startTime": slot_start_iso,
                "settlementPeriod": actual_row.get("settlementPeriod", period) if actual_row else period,
                "actual_mw": round(actual_mw, 1) if actual_mw is not None else None,
                "forecast_mw": round(forecast_mw, 1) if forecast_mw is not None else None,
                "publishTime": pub_time,
                "error_mw": round(err_mw, 1) if err_mw is not None else None,
            }
        )

    # 4. Calculate Errors & Daily Totals
    actual_vals = [s["actual_mw"] for s in timeseries if s["actual_mw"] is not None]
    forecast_vals = [s["forecast_mw"] for s in timeseries if s["forecast_mw"] is not None]
    error_vals = [s["error_mw"] for s in timeseries if s["error_mw"] is not None]

    total_actual_mwh = sum(actual_vals) * 0.5 if actual_vals else 0.0
    total_forecast_mwh = sum(forecast_vals) * 0.5 if forecast_vals else 0.0

    avg_actual_mw = statistics.mean(actual_vals) if actual_vals else 0.0
    avg_forecast_mw = statistics.mean(forecast_vals) if forecast_vals else 0.0

    mae_mw = statistics.mean([abs(e) for e in error_vals]) if error_vals else 0.0
    rmse_mw = math.sqrt(statistics.mean([e**2 for e in error_vals])) if error_vals else 0.0
    mean_bias_mw = statistics.mean(error_vals) if error_vals else 0.0

    shortfall_vals = [max(0.0, e) for e in error_vals]
    if len(shortfall_vals) >= 2:
        p90_shortfall_mw = statistics.quantiles(shortfall_vals, n=100, method="inclusive")[89]
    elif len(shortfall_vals) == 1:
        p90_shortfall_mw = shortfall_vals[0]
    else:
        p90_shortfall_mw = 0.0

    summary = {
        "total_actual_mwh": round(total_actual_mwh, 1),
        "total_forecast_mwh": round(total_forecast_mwh, 1),
        "avg_actual_mw": round(avg_actual_mw, 1),
        "avg_forecast_mw": round(avg_forecast_mw, 1),
        "mae_mw": round(mae_mw, 1),
        "rmse_mw": round(rmse_mw, 1),
        "mean_bias_mw": round(mean_bias_mw, 1),
        "p90_shortfall_mw": round(p90_shortfall_mw, 1),
    }

    return {
        "target_date": target_date,
        "decision_cutoff_utc": cutoff_str,
        "summary": summary,
        "timeseries": timeseries,
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
