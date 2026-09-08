export interface ClockStatus {
  ts_sim: string;
  speed: number;
  is_paused: boolean;
  loop_enabled?: boolean;
  loop_start?: string;
  loop_end?: string;
}

export interface SystemStatus {
  status: string;
  clock: ClockStatus;
  mqtt_connected: boolean;
  bess_connected: boolean;
  active_bess: string[];
  stage: string;
}

export interface HealthResponse {
  status: string;
  service: string;
  database: boolean;
}

export interface BessTelemetryTick {
  bess_id?: string;
  soc_pct?: number;
  soh_pct?: number;
  soe_kwh?: number;
  power_kw?: number;
  voltage_v?: number;
  current_a?: number;
  temp_c?: number;
  state?: string;
  alarms?: Record<string, unknown> | unknown[];
  aux_kw?: number;
  heat_kw?: number;
  capacity_actual_kwh?: number;
  available_charge_kw?: number;
  available_discharge_kw?: number;
}

export interface SiteTick {
  load_kw: number;
  pv_kw: number;
  /** BESS auxiliary draw (HVAC, BMS, PCS idle) fed from the AC bus */
  aux_kw?: number;
}

export interface GridTick {
  import_kw: number;
  export_kw: number;
}

export interface MarketTick {
  price_dam?: number;
  price_buy?: number;
  price_sell?: number;
  level?: 'CHEAP' | 'MID' | 'PEAK';
}

export interface EmsTick {
  setpoint_kw?: number;
  reason?: string;
  schedule_id?: string | null;
  state?: 'DISPATCHING' | 'SAFE_MODE' | 'NO_SCHEDULE';
  is_optimizing?: boolean;
}

export interface FinanceTick {
  today_net_uah?: number;
  today_baseline_uah?: number;
}

export interface WsTickPayload {
  type: 'tick';
  clock: ClockStatus;
  bess: BessTelemetryTick;
  site: SiteTick;
  grid: GridTick;
  market: MarketTick;
  ems: EmsTick;
  finance: FinanceTick;
}

export interface WsEventPayload {
  type: 'event';
  event: string;
  reason?: string;
  severity?: 'INFO' | 'WARNING' | 'ALARM';
  ts: string;
  schedule_id?: string;
  strategy?: string;
  items_count?: number;
  expected_profit_uah?: number;
}

export interface ScheduleItem {
  ts: string;
  setpoint_kw: number;
  reason: string;
}

export interface ScheduleResponse {
  id: string;
  strategy: { name: string; capacity_kwh?: number; [key: string]: any } | string;
  created_at_sim: string;
  horizon_start: string;
  horizon_end: string;
  expected_profit_uah?: number;
  solver_status?: string;
  solve_time_ms?: number;
  items: ScheduleItem[];
}

export interface MlModelInfo {
  name: string;
  version: string;
  target: string;
  trained_at: string | null;
  metrics: {
    mae?: number;
    mape?: number;
    rmse?: number;
    spearman_rank_corr?: number;
  };
  artifact_path: string;
  is_active: boolean;
}

export interface ForecastPoint {
  ts: string;
  target: string;
  model_name: string;
  model_version: string;
  value: number;
  p10?: number | null;
  p90?: number | null;
  horizon_h: number;
}

export interface BacktestResult {
  model: string;
  version: string;
  net_uah: number;
  revenue_uah: number;
  cost_uah: number;
  degradation_uah: number;
  cycles: number;
  pct_of_perfect_foresight: number;
}

export interface SettingsSchemaResponse {
  section: string;
  schema: {
    properties?: Record<string, {
      title?: string;
      description?: string;
      type?: string;
      default?: any;
      minimum?: number;
      maximum?: number;
      enum?: any[];
    }>;
    required?: string[];
  };
  requires_restart: string[];
}

export interface CsvPreviewResponse {
  detected_type: string;
  columns: string[];
  total_rows: number;
  preview_rows: Record<string, any>[];
  is_valid: boolean;
  errors: string[];
}

export interface HeatmapDataResponse {
  type: string;
  x_categories: string[];
  y_categories: string[];
  data: [number, number, number][];
  min_value: number;
  max_value: number;
  unit: string;
  total_samples: number;
}

export interface TimeSeriesDataPoint {
  ts: string;
  value: number;
}

export interface TimeSeriesResponse {
  type: string;
  step: string;
  count: number;
  data: TimeSeriesDataPoint[];
}

export interface ReportSummaryKPIs {
  total_cost_baseline_uah: number;
  total_cost_actual_uah: number;
  net_savings_uah: number;
  export_revenue_uah: number;
  degradation_uah: number;
  net_benefit_uah: number;
  total_import_kwh: number;
  total_export_kwh: number;
  equivalent_cycles: number;
  payback_years: number | null;
  hours_count: number;
}

export interface ReportHourlyPoint {
  ts: string;
  cost_baseline_uah: number;
  cost_actual_uah: number;
  net_savings_uah: number;
  revenue_uah: number;
  degradation_uah: number;
  net_uah: number;
  import_kwh: number;
  export_kwh: number;
  price_buy: number;
  price_sell: number;
}

export interface ReportSummaryResponse {
  from: string | null;
  to: string | null;
  summary: ReportSummaryKPIs;
  hourly: ReportHourlyPoint[];
}

export interface StrategyComparisonItem {
  strategy: string;
  baseline_cost_uah: number;
  actual_cost_uah: number;
  net_savings_uah: number;
  export_revenue_uah: number;
  degradation_uah: number;
  net_benefit_uah: number;
  total_charge_kwh: number;
  total_discharge_kwh: number;
  equivalent_cycles: number;
  solver_status?: string;
  solve_time_ms?: number;
  error?: string;
}

export interface StrategyComparisonResponse {
  date: string;
  comparison: StrategyComparisonItem[];
}

export interface DispatchLogItem {
  ts: string;
  setpoint_kw: number;
  actual_kw: number | null;
  reason: string | null;
  schedule_id: string | null;
  override: boolean;
}

export interface PaginatedDispatchLogResponse {
  items: DispatchLogItem[];
  total: number;
  page: number;
  limit: number;
}

export interface SimulationTemplate {
  id: string;
  name: string;
  description: string;
  start_time: string;
  duration_days: number;
  loop_cyclic: boolean;
  default_loop_days: number;
  max_loop_days: number;
  battery_capacity_kwh: number;
  battery_power_kw: number;
  soc_min_pct: number;
  soc_max_pct: number;
  reserve_soc_pct: number;
  initial_soc_pct: number;
  site_day_load_kw: number;
  site_night_load_kw: number;
  pv_peak_kw: number;
  strategy: string;
  price_source: string;
  is_default: boolean;
}

export interface DailyReportItem {
  date: string;
  day_index: number;
  baseline_cost_uah: number;
  actual_cost_uah: number;
  degradation_uah: number;
  net_saving_uah: number;
  saving_pct: number;
  cycles: number;
  charged_kwh: number;
  discharged_kwh: number;
  baseline_peak_kw: number;
  actual_peak_kw: number;
  peak_reduction_kw: number;
}

export interface TemplateReportKPI {
  baseline_cost_uah: number;
  actual_cost_uah: number;
  net_savings_uah: number;
  savings_pct: number;
  total_degradation_uah: number;
  total_charged_kwh: number;
  total_discharged_kwh: number;
  total_cycles: number;
  avg_daily_savings_uah: number;
  peak_shaving_kw: number;
  peak_shaving_pct: number;
  total_load_kwh: number;
  total_pv_kwh: number;
}

export interface TemplateReportResponse {
  template_id: string;
  template_name: string;
  analyzed_days: number;
  start_date: string;
  end_date: string;
  battery: {
    capacity_kwh: number;
    power_kw: number;
  };
  kpi: TemplateReportKPI;
  daily: DailyReportItem[];
}



