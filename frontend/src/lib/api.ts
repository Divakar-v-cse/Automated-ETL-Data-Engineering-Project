/**
 * Thin typed wrapper around the FastAPI backend.
 * When the frontend is served by FastAPI the API is same-origin; during `vite
 * dev` the proxy in vite.config.ts forwards /api and /health to port 8010.
 */
export const API_BASE =
  (import.meta as any).env?.VITE_API_BASE?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const text = await res.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : body?.detail
          ? JSON.stringify(body.detail)
          : `HTTP ${res.status}`;
    throw new ApiError(res.status, detail);
  }
  return body as T;
}

export const api = {
  health: () => request<any>("/health"),
  overview: (trendDays = 30) =>
    request<any>(`/api/dashboard/overview?trend_days=${trendDays}`),
  sales: (days = 90, months = 24, top = 10) =>
    request<any>(`/api/analytics/sales?days=${days}&months=${months}&top=${top}`),
  customers: (page = 1, pageSize = 25, sortBy = "monetary") =>
    request<any>(
      `/api/analytics/customers?page=${page}&page_size=${pageSize}&sort_by=${sortBy}`,
    ),
  products: (
    page = 1,
    pageSize = 25,
    sortBy = "revenue",
    order = "desc",
    category = "",
    q = "",
  ) =>
    request<any>(
      `/api/analytics/products?page=${page}&page_size=${pageSize}` +
        `&sort_by=${sortBy}&sort_order=${order}` +
        (category ? `&category=${encodeURIComponent(category)}` : "") +
        (q ? `&q=${encodeURIComponent(q)}` : ""),
    ),
  orders: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).reduce<Record<string, string>>((acc, [k, v]) => {
        if (v !== "" && v !== undefined && v !== null) acc[k] = String(v);
        return acc;
      }, {}),
    ).toString();
    return request<any>(`/api/analytics/orders${qs ? `?${qs}` : ""}`);
  },
  orderDetail: (id: string) =>
    request<any>(`/api/analytics/orders/${encodeURIComponent(id)}`),
  pipelineStatus: () => request<any>("/api/pipeline/status"),
  pipelineHistory: (page = 1, pageSize = 20, status = "", dagId = "", runId?: number) =>
    request<any>(
      `/api/pipeline/history?page=${page}&page_size=${pageSize}` +
        (status ? `&status=${status}` : "") +
        (dagId ? `&dag_id=${dagId}` : "") +
        (runId ? `&run_id=${runId}` : ""),
    ),
  trigger: (body: {
    dag_id: string;
    incremental?: boolean;
    skip_reporting?: boolean;
    mode?: "async" | "sync";
  }) =>
    request<any>("/api/pipeline/trigger", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  backfill: (body: {
    start_date: string;
    end_date: string;
    dag_id?: string;
    incremental?: boolean;
  }) =>
    request<any>("/api/pipeline/backfill", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  schedule: () => request<any>("/api/pipeline/schedule"),
  watermarks: () => request<any>("/api/pipeline/watermarks"),
  quality: (runId?: number, page = 1, pageSize = 20, reason = "") =>
    request<any>(
      `/api/data-quality?page=${page}&page_size=${pageSize}` +
        (runId ? `&run_id=${runId}` : "") +
        (reason ? `&reason=${encodeURIComponent(reason)}` : ""),
    ),
  qualityChecks: () => request<any>("/api/data-quality/checks"),
  reports: (page = 1, pageSize = 20, type = "") =>
    request<any>(
      `/api/reports?page=${page}&page_size=${pageSize}` +
        (type ? `&report_type=${type}` : ""),
    ),
  report: (id: number) => request<any>(`/api/reports/${id}`),
};

export const reportDownloadUrl = (id: number) =>
  `${API_BASE}/api/reports/${id}/download`;
export const reportHtmlUrl = (id: number) =>
  `${API_BASE}/api/reports/${id}/html`;
export const docsUrl = `${API_BASE}/docs`;
