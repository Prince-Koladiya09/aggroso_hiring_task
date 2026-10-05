const API_BASE = '/api';

export class ApiError extends Error {
  status: number;
  code?: string;
  ruleIds: string[];
  fields: { field: string; message: string }[];
  correlationId?: string;
  constructor(message: string, status: number, extra: Partial<ApiError> = {}) {
    super(message);
    this.status = status;
    this.code = extra.code;
    this.ruleIds = extra.ruleIds || [];
    this.fields = extra.fields || [];
    this.correlationId = extra.correlationId;
  }
}

export async function apiRequest<T = any>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json', ...((options.headers as any) || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${endpoint}`, { ...options, headers });
  } catch {
    throw new ApiError('Cannot reach the server. Check your connection and try again.', 0, { code: 'NETWORK' });
  }

  if (!response.ok) {
    let msg = response.statusText || 'Request failed';
    let extra: Partial<ApiError> = {};
    try {
      const body = await response.json();
      const e = body.error;
      msg = e?.message || (typeof body.detail === 'string' ? body.detail : msg);
      extra = { code: e?.code, ruleIds: e?.rule_ids, fields: e?.fields, correlationId: e?.correlation_id };
    } catch { /* non-JSON error */ }
    if (response.status === 401 && endpoint !== '/auth/login') {
      localStorage.removeItem('token');
      window.dispatchEvent(new Event('auth-expired'));
    }
    throw new ApiError(msg, response.status, extra);
  }

  const ct = response.headers.get('content-type') || '';
  if (ct.includes('application/json')) return response.json();
  return response.text() as any;
}

/** Download a file (needs the bearer token, so we can't use a plain link). */
export async function downloadFile(endpoint: string, filename: string): Promise<void> {
  const token = localStorage.getItem('token');
  const res = await fetch(`${API_BASE}${endpoint}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    let m = 'Download failed';
    try { m = (await res.json()).error?.message || m; } catch { /* ignore */ }
    throw new ApiError(m, res.status);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
