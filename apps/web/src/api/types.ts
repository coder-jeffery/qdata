export type Overview = {
  dataset: { version: string | null; source?: string; error?: string };
  daily_bar: {
    min_date?: string;
    max_date?: string;
    rows?: number;
    days?: number;
    n_codes?: number;
    error?: string;
  };
  factor_monitor: {
    date?: string;
    n_alerts?: number;
    universe_size?: number;
    min_coverage?: number;
    via?: string;
  };
  paper: {
    session_id?: string;
    asof?: string;
    total_asset?: number;
    cash?: number;
    market_value?: number;
    n_filled?: number;
    n_rejected?: number;
    pnl_vs_initial?: number;
    mark_date?: string;
  };
  generated_at?: string;
};

export type PaperSessionMeta = {
  session_id: string;
  asof?: string;
  created_at?: string;
  n_filled?: number;
  n_rejected?: number;
  last_mark_date?: string;
  last_mark_total_asset?: number;
  last_mark_pnl_vs_initial?: number;
  from_experiment?: { enabled?: boolean; experiment_id?: string };
};

export type PaperSessionDetail = {
  session_id: string;
  meta: PaperSessionMeta;
  account: { cash?: number; market_value?: number; total_asset?: number };
  orders: Array<Record<string, unknown>>;
  positions: Array<Record<string, unknown>>;
  rejects: Array<Record<string, unknown>>;
  mark_latest: Record<string, unknown>;
  marks: Array<Record<string, unknown>>;
};

export type HealthPayload = {
  summary: {
    security_master?: number;
    daily_bar_max?: string;
    daily_bar_days?: number;
    daily_bar_rows?: number;
    latest_published?: string;
    last_drift_pct?: number | null;
    extras_stale?: number;
    watermarks?: Array<{
      name: string;
      min_date?: string;
      max_date?: string;
      rows?: number;
      days?: number;
      ok?: boolean;
      note?: string;
    }>;
  };
  lag: Array<{ table: string; max_date?: string; lag_days?: number; status?: string }>;
  publications: Array<Record<string, unknown>>;
  error?: string;
};

export type FactorCoverage = {
  trade_date?: string | null;
  items: Array<{
    trade_date?: string;
    factor?: string;
    n_valid?: number;
    universe?: number;
    coverage?: number;
    p50?: number;
    mean?: number;
  }>;
  dates: string[];
  error?: string;
};

export type ExperimentMeta = {
  experiment_id: string;
  created_at?: string;
  dataset_version?: string;
  n_cells?: number;
  n_ok?: number;
  n_fail?: number;
  path?: string;
  spec?: Record<string, unknown>;
};

export type SignalMeta = {
  signal_id: string;
  asof?: string;
  factor?: string;
  weight_method?: string;
  universe?: string;
  top_n?: number;
  path?: string;
};

export type MonitorPayload = {
  report: Record<string, unknown>;
  coverage: Array<Record<string, unknown>>;
  dates: string[];
};

export type BacktestPayload = {
  items: Array<Record<string, unknown>>;
  matrix: Array<Record<string, unknown>>;
  count: number;
  error?: string;
};
