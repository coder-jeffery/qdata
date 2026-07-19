import type {
  BacktestPayload,
  ExperimentMeta,
  FactorCoverage,
  HealthPayload,
  MonitorPayload,
  Overview,
  PaperSessionDetail,
  PaperSessionMeta,
  SignalMeta,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let detail: unknown = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = body.detail || body;
    } catch {
      detail = (await res.text()) || detail;
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export type JobRecord = {
  job_id: string;
  type: string;
  status: "queued" | "running" | "succeeded" | "failed" | string;
  payload?: Record<string, unknown>;
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  result?: Record<string, unknown> | null;
  error?: string | null;
};

export type AlertItem = {
  id: string;
  level: "error" | "warn" | string;
  source: string;
  title: string;
  message: string;
  ts?: string | null;
  href?: string;
};

export type AlertPayload = {
  items: AlertItem[];
  count: number;
  n_error: number;
  n_warn: number;
  generated_at?: string;
};

export type QuoteRow = {
  exchange_code?: string;
  name?: string;
  price?: number | string;
  open?: number | string;
  high?: number | string;
  low?: number | string;
  pre_close?: number | string;
  volume?: number | string;
  amount?: number | string;
  snapshot_ts?: string;
  [k: string]: unknown;
};

export const api = {
  overview: () => request<Overview>("/api/overview"),

  paperSessions: (limit = 30) =>
    request<{ items: PaperSessionMeta[]; count: number }>(`/api/paper/sessions?limit=${limit}`),
  paperSession: (id: string) =>
    request<PaperSessionDetail>(`/api/paper/sessions/${encodeURIComponent(id)}`),
  paperCompare: (ids: string[]) =>
    request<{ items: Array<Record<string, unknown>>; count: number }>(
      `/api/paper/compare?ids=${encodeURIComponent(ids.join(","))}`,
    ),
  paperMark: (id: string, markDate?: string) =>
    request<{
      ok: boolean;
      async?: boolean;
      job_id?: string;
      status?: string;
      mark?: Record<string, unknown>;
    }>(`/api/paper/sessions/${encodeURIComponent(id)}/mark`, {
      method: "POST",
      body: JSON.stringify(markDate ? { mark_date: markDate, async: true } : { async: true }),
    }),

  dataHealth: () => request<HealthPayload>("/api/data/health"),
  dataFinance: () =>
    request<{
      summary: Record<string, unknown>;
      monthly: Array<Record<string, unknown>>;
      pit: Array<Record<string, unknown>>;
      lag: Record<string, unknown>;
      error?: string;
    }>("/api/data/finance"),

  factorCoverage: (date?: string) =>
    request<FactorCoverage>(
      date ? `/api/factors/coverage?date=${encodeURIComponent(date)}` : "/api/factors/coverage",
    ),

  universe: (date?: string, index = "000905.SH") =>
    request<{
      trade_date?: string;
      sizes: Array<Record<string, unknown>>;
      industry: Array<Record<string, unknown>>;
      coverage: Record<string, unknown>;
      error?: string;
    }>(
      `/api/research/universe?index=${encodeURIComponent(index)}${
        date ? `&date=${encodeURIComponent(date)}` : ""
      }`,
    ),

  experiments: (limit = 30) =>
    request<{ items: ExperimentMeta[]; count: number }>(`/api/experiments?limit=${limit}`),
  experiment: (id: string) =>
    request<{
      experiment_id: string;
      meta: ExperimentMeta;
      summary: Array<Record<string, unknown>>;
    }>(`/api/experiments/${encodeURIComponent(id)}`),

  signals: (limit = 30) =>
    request<{ items: SignalMeta[]; count: number }>(`/api/signals?limit=${limit}`),
  signal: (id: string) =>
    request<{
      meta: SignalMeta;
      weights: Array<Record<string, unknown>>;
      exposure: Array<Record<string, unknown>>;
      tradability: Array<Record<string, unknown>>;
      path?: string;
    }>(`/api/signals/${encodeURIComponent(id)}`),
  signalJudge: (id: string, topN = 20) =>
    request<{
      ok: boolean;
      async?: boolean;
      job_id?: string;
      status?: string;
      n?: number;
      summary?: Array<Record<string, unknown>>;
      cards?: Array<Record<string, unknown>>;
    }>(`/api/signals/${encodeURIComponent(id)}/judge`, {
      method: "POST",
      body: JSON.stringify({ top_n: topN, async: true }),
    }),

  monitor: (date?: string) =>
    request<MonitorPayload>(date ? `/api/monitor/${encodeURIComponent(date)}` : "/api/monitor"),

  backtests: (limit = 20) => request<BacktestPayload>(`/api/backtests?limit=${limit}`),
  backtest: (runId: string) =>
    request<{
      run_id: string;
      meta: Record<string, unknown>;
      metrics: Record<string, unknown>;
      equity: Array<Record<string, unknown>>;
      fills: Array<Record<string, unknown>>;
    }>(`/api/backtests/${encodeURIComponent(runId)}`),

  judgment: (code: string, asof?: string) =>
    request<{ ok: boolean; card: Record<string, unknown> }>(
      `/api/research/judgment/${encodeURIComponent(code)}${
        asof ? `?asof=${encodeURIComponent(asof)}` : ""
      }`,
    ),

  researchTa: (
    code: string,
    opts?: { start?: string; end?: string; adjust?: "post" | "pre" | "none" },
  ) => {
    const q = new URLSearchParams();
    if (opts?.start) q.set("start", opts.start);
    if (opts?.end) q.set("end", opts.end);
    if (opts?.adjust) q.set("adjust", opts.adjust);
    const qs = q.toString();
    return request<{
      ok: boolean;
      code: string;
      adjust: string;
      count: number;
      start?: string;
      end?: string;
      last_close?: number | null;
      bars: Array<{
        trade_date: string;
        open: number;
        high: number;
        low: number;
        close: number;
        volume: number;
        ma5: number | null;
        ma10: number | null;
        boll_mid: number | null;
        boll_upper: number | null;
        boll_lower: number | null;
        dif: number | null;
        dea: number | null;
        macd_hist: number | null;
        k: number | null;
        d: number | null;
        j: number | null;
      }>;
    }>(`/api/research/ta/${encodeURIComponent(code)}${qs ? `?${qs}` : ""}`);
  },

  paperFromExperiment: (experimentId: string, rankBy = "sharpe") =>
    request<{
      ok: boolean;
      async?: boolean;
      job_id?: string;
      status?: string;
      result?: Record<string, unknown>;
    }>("/api/jobs/paper-from-experiment", {
      method: "POST",
      body: JSON.stringify({ experiment_id: experimentId, rank_by: rankBy, async: true }),
    }),

  jobs: (limit = 30) =>
    request<{ items: JobRecord[]; count: number }>(`/api/jobs?limit=${limit}`),
  job: (jobId: string) => request<JobRecord>(`/api/jobs/${encodeURIComponent(jobId)}`),
  enqueueJob: (type: string, payload: Record<string, unknown> = {}) =>
    request<{ ok: boolean; job_id: string; status: string; type: string }>("/api/jobs", {
      method: "POST",
      body: JSON.stringify({ type, payload }),
    }),

  alerts: () => request<AlertPayload>("/api/alerts"),

  realtimeQuotes: (codes?: string[], source = "easyquotation") =>
    request<{
      source: string;
      quotes: QuoteRow[];
      n: number;
      snapshot_ts?: string | null;
      stale?: boolean;
      error?: string;
    }>(
      `/api/realtime/quotes?source=${encodeURIComponent(source)}${
        codes?.length ? `&codes=${encodeURIComponent(codes.join(","))}` : ""
      }`,
    ),
  realtimeRefresh: (codes?: string[], source = "easyquotation") =>
    request<{
      ok: boolean;
      async?: boolean;
      job_id?: string;
      status?: string;
      quotes?: QuoteRow[];
      n?: number;
    }>("/api/realtime/refresh", {
      method: "POST",
      body: JSON.stringify({ source, codes, async: true }),
    }),
};
