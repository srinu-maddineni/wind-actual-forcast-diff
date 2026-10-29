import { useEffect, useState } from 'react'
import './index.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'

function formatTime(value) {
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
    hour12: false,
  }).format(new Date(value))
}

function formatNumber(value) {
  return value == null
    ? '—'
    : Number(value).toLocaleString('en-GB', { maximumFractionDigits: 1 })
}

export default function App() {
  const [targetDate, setTargetDate] = useState('2026-01-15')
  const [timeseries, setTimeseries] = useState([])
  const [summary, setSummary] = useState(null)
  const [decisionCutoff, setDecisionCutoff] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    setTimeseries([])
    setSummary(null)

    fetch(`${API_BASE}/wind-data?target_date=${targetDate}`, { signal: controller.signal })
      .then(async (response) => {
        const body = await response.json()
        if (!response.ok) {
          throw new Error(body.detail || `Request failed (${response.status})`)
        }
        return body
      })
      .then((body) => {
        setTimeseries(body.timeseries || body.slots || [])
        setSummary(body.summary || null)
        setDecisionCutoff(body.decision_cutoff_utc || '')
      })
      .catch((cause) => {
        if (cause.name !== 'AbortError') {
          setError(cause.message || 'Unable to load generation data.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => controller.abort()
  }, [targetDate])

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <h1>Wind Generation</h1>
          <p>Actual vs Day-Ahead Forecast · Half-Hourly Settlement Periods (UTC)</p>
        </div>
        <label className="date-picker">
          <span>Target Date</span>
          <input
            type="date"
            value={targetDate}
            onChange={(event) => setTargetDate(event.target.value)}
          />
        </label>
      </header>

      <section className="data-panel" aria-live="polite">
        <div className="table-heading">
          <div>
            <h2>{targetDate}</h2>
            <p>
              {loading
                ? 'Loading data…'
                : `${timeseries.length} settlement periods · Cutoff: ${decisionCutoff || '—'}`}
            </p>
          </div>
          <span className="units">Power (MW) / Energy (MWh)</span>
        </div>

        {!loading && !error && summary && (
          <div className="summary-row">
            <section className="summary-item">
              <h3>Totals & Averages</h3>
              <p><strong>{formatNumber(summary.total_actual_mwh)}</strong> MWh Actual</p>
              <p><strong>{formatNumber(summary.total_forecast_mwh)}</strong> MWh Forecast</p>
              <p><strong>{formatNumber(summary.avg_actual_mw)}</strong> MW Avg Actual</p>
              <p><strong>{formatNumber(summary.avg_forecast_mw)}</strong> MW Avg Forecast</p>
            </section>
            <section className="summary-item">
              <h3>Error & Shortfall Metrics</h3>
              <p>MAE: <strong>{formatNumber(summary.mae_mw)}</strong> MW</p>
              <p>RMSE: <strong>{formatNumber(summary.rmse_mw)}</strong> MW</p>
              <p>Mean Bias: <strong>{formatNumber(summary.mean_bias_mw)}</strong> MW</p>
              <p>P90 Shortfall: <strong>{formatNumber(summary.p90_shortfall_mw)}</strong> MW</p>
            </section>
          </div>
        )}

        {error && <p className="message error" role="alert">{error}</p>}
        {!error && loading && <p className="message">Loading generation data…</p>}
        {!error && !loading && (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">Period</th>
                  <th scope="col">Start Time (UTC)</th>
                  <th scope="col" className="numeric">Actual (MW)</th>
                  <th scope="col" className="numeric">Forecast (MW)</th>
                  <th scope="col" className="numeric">Error (MW)</th>
                  <th scope="col">Forecast Publish Time</th>
                </tr>
              </thead>
              <tbody>
                {timeseries.map((slot) => {
                  const actual = slot.actual_mw ?? slot.generation
                  const forecast = slot.forecast_mw ?? slot.forecast_generation
                  return (
                    <tr key={slot.settlementPeriod}>
                      <td>{String(slot.settlementPeriod).padStart(2, '0')}</td>
                      <td>{formatTime(slot.startTime)}</td>
                      <td className="numeric">{formatNumber(actual)}</td>
                      <td className="numeric">{formatNumber(forecast)}</td>
                      <td className="numeric">
                        {slot.error_mw == null ? '—' : formatNumber(slot.error_mw)}
                      </td>
                      <td>{slot.publishTime ? formatTime(slot.publishTime) : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {timeseries.length === 0 && <p className="message">No settlement periods were returned.</p>}
          </div>
        )}
      </section>
      <footer>
        Forecasts use the latest publication available before {decisionCutoff || '09:30 UTC on D-1'}.
      </footer>
    </main>
  )
}
