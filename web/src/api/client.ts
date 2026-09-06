import { SystemStatus, HealthResponse, MlModelInfo, ForecastPoint, BacktestResult } from '../types';

/**
 * FastAPI returns `detail` either as a string or as a list of validation objects.
 * Rendering the object directly produces "[object Object]", which hides the reason
 * the save failed — flatten it to readable text instead.
 */
async function errorText(response: Response, fallback: string): Promise<string> {
  const body = await response.json().catch(() => null);
  const detail = (body as any)?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: any) => {
        const loc = Array.isArray(d?.loc) ? d.loc.filter((p: any) => p !== 'body').join('.') : '';
        return loc ? `${loc}: ${d?.msg ?? ''}` : String(d?.msg ?? JSON.stringify(d));
      })
      .join('; ');
  }
  if (detail) return JSON.stringify(detail);
  return fallback;
}

export async function fetchSystemStatus(): Promise<SystemStatus> {
  const response = await fetch('/api/status');
  if (!response.ok) {
    throw new Error(`Failed to fetch status: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch('/api/health');
  if (!response.ok) {
    throw new Error(`Failed to fetch health: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchMlModels(): Promise<MlModelInfo[]> {
  const response = await fetch('/api/ml/models');
  if (!response.ok) {
    throw new Error(`Failed to fetch models: ${response.statusText}`);
  }
  return response.json();
}

export async function trainModel(payload: {
  target: string;
  model: string;
  version: string;
  from_date: string;
  to_date: string;
}): Promise<{ status: string; message: string }> {
  const response = await fetch('/api/ml/train', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`Failed to start training: ${response.statusText}`);
  }
  return response.json();
}

export async function activateModel(name: string, version: string): Promise<{ status: string }> {
  const response = await fetch(`/api/ml/models/${name}/${version}/activate`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error(`Failed to activate model: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchForecasts(target = 'price', limit = 48): Promise<ForecastPoint[]> {
  const response = await fetch(`/api/forecasts?target=${target}&limit=${limit}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch forecasts: ${response.statusText}`);
  }
  return response.json();
}

export async function runForecastNow(target = 'price'): Promise<{ status: string }> {
  const response = await fetch(`/api/forecasts/run?target=${target}`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error(`Failed to trigger forecast: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchBacktestResults(): Promise<BacktestResult[]> {
  const response = await fetch('/api/ml/backtest');
  if (!response.ok) {
    throw new Error(`Failed to fetch backtest results: ${response.statusText}`);
  }
  return response.json();
}

// ── Settings API ─────────────────────────────────────────────────────────────

export async function fetchSettingsSchema(section: string): Promise<import('../types').SettingsSchemaResponse> {
  const response = await fetch(`/api/settings/${section}/schema`);
  if (!response.ok) {
    throw new Error(`Failed to fetch schema for ${section}: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchSettingsSection(section: string): Promise<Record<string, any>> {
  const response = await fetch(`/api/settings/${section}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch settings for ${section}: ${response.statusText}`);
  }
  return response.json();
}

export async function updateSettingsSection(
  section: string,
  payload: Record<string, any>
): Promise<{ status: string; settings: Record<string, any> }> {
  const response = await fetch(`/api/settings/${section}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await errorText(response, `Failed to update ${section}`));
  }
  return response.json();
}

export async function injectFault(
  type: string,
  duration_s = 60
): Promise<{ status: string; fault_type: string }> {
  const response = await fetch('/api/bess/fault-injection', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type, duration_s, enabled: true }),
  });
  if (!response.ok) {
    throw new Error(`Failed to inject fault: ${response.statusText}`);
  }
  return response.json();
}

// ── Data API ─────────────────────────────────────────────────────────────────

export async function previewCsvData(
  file: File,
  type?: string
): Promise<import('../types').CsvPreviewResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const url = type ? `/api/data/preview?type=${type}` : '/api/data/preview';
  const response = await fetch(url, {
    method: 'POST',
    body: formData,
  });
  if (!response.ok) {
    throw new Error(`Failed to preview CSV: ${response.statusText}`);
  }
  return response.json();
}

export async function importCsvData(
  file: File,
  type: 'price' | 'load'
): Promise<{ status: string; imported_rows: number }> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch(`/api/data/import?type=${type}`, {
    method: 'POST',
    body: formData,
  });
  if (!response.ok) {
    throw new Error(await errorText(response, 'Failed to import CSV'));
  }
  return response.json();
}

export async function generateSyntheticData(payload: {
  start_date: string;
  end_date: string;
  seed: number;
  overwrite: boolean;
}): Promise<{ status: string; prices_count: number; load_count: number }> {
  const response = await fetch('/api/data/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await errorText(response, 'Failed to generate synthetic data'));
  }
  return response.json();
}

export async function fetchHeatmapData(
  type = 'price',
  fromDate?: string,
  toDate?: string
): Promise<import('../types').HeatmapDataResponse> {
  const params = new URLSearchParams({ type });
  if (fromDate) params.append('from', fromDate);
  if (toDate) params.append('to', toDate);

  const response = await fetch(`/api/data/heatmap?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch heatmap data: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchTimeSeries(
  type: 'price' | 'load' | 'pv',
  from: string,
  to: string,
  step = '1h'
): Promise<import('../types').TimeSeriesResponse> {
  const params = new URLSearchParams({ type, from, to, step });
  const response = await fetch(`/api/data/series?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch time series: ${response.statusText}`);
  }
  return response.json();
}

// ── Reports API ──────────────────────────────────────────────────────────────

export async function fetchReportSummary(
  fromDate?: string,
  toDate?: string
): Promise<import('../types').ReportSummaryResponse> {
  const params = new URLSearchParams({ format: 'json' });
  if (fromDate) params.append('from', fromDate);
  if (toDate) params.append('to', toDate);

  const response = await fetch(`/api/reports/summary?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch report summary: ${response.statusText}`);
  }
  return response.json();
}

export async function downloadReportFile(
  format: 'xlsx' | 'csv',
  fromDate?: string,
  toDate?: string
): Promise<void> {
  const params = new URLSearchParams({ format });
  if (fromDate) params.append('from', fromDate);
  if (toDate) params.append('to', toDate);

  const url = `/api/reports/summary?${params.toString()}`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to download report: ${response.statusText}`);
  }
  const blob = await response.blob();
  const downloadUrl = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = downloadUrl;
  a.download = `ems_report.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(downloadUrl);
}

export async function compareStrategies(
  date?: string,
  strategies = 'TOU_SIMPLE,ARBITRAGE,PEAK_SHAVING,SELF_CONSUMPTION'
): Promise<import('../types').StrategyComparisonResponse> {
  const params = new URLSearchParams({ strategies });
  if (date) params.append('date', date);

  const response = await fetch(`/api/reports/compare-strategies?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to compare strategies: ${response.statusText}`);
  }
  return response.json();
}

// ── Logs & Schedules API ─────────────────────────────────────────────────────

export async function fetchPaginatedDispatchLog(
  page = 1,
  limit = 50,
  reason?: string,
  override?: boolean,
  scheduleId?: string
): Promise<import('../types').PaginatedDispatchLogResponse> {
  const params = new URLSearchParams({ page: String(page), limit: String(limit) });
  if (reason) params.append('reason', reason);
  if (override !== undefined) params.append('override', String(override));
  if (scheduleId) params.append('schedule_id', scheduleId);

  const response = await fetch(`/api/dispatch/log?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch dispatch log: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchScheduleById(
  scheduleId: string
): Promise<import('../types').ScheduleResponse> {
  const response = await fetch(`/api/schedules/${scheduleId}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch schedule ${scheduleId}: ${response.statusText}`);
  }
  return response.json();
}


