/**
 * API client.
 *
 * Works in three environments without configuration:
 *   - GitHub Codespaces  (rewrites the -3000 port suffix to -8000)
 *   - Local Docker       (localhost:8000)
 *   - Custom             (VITE_API_URL)
 */

function resolveBase() {
  if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL;

  const { hostname, protocol } = window.location;

  // Codespaces: name-3000.app.github.dev  ->  name-8000.app.github.dev
  if (hostname.includes('.app.github.dev')) {
    return `${protocol}//${hostname.replace(/-3000\./, '-8000.')}`;
  }
  // Gitpod
  if (hostname.includes('.gitpod.io')) {
    return `${protocol}//${hostname.replace(/^3000-/, '8000-')}`;
  }
  return 'http://localhost:8000';
}

export const API_BASE = resolveBase();

const TOKEN_KEY = 'stp_token';
const USER_KEY = 'stp_user';

export const auth = {
  get token() { return sessionStorage.getItem(TOKEN_KEY); },
  get user() {
    const raw = sessionStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  },
  set(token, user) {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  clear() {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
  },
};

class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`;
  if (options.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch (e) {
    throw new ApiError(
      `Cannot reach the trading service at ${API_BASE}. Check the backend is running.`,
      0, null
    );
  }

  if (res.status === 401) {
    auth.clear();
    window.location.reload();
    throw new ApiError('Session expired. Sign in again.', 401, null);
  }

  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }

  if (!res.ok) {
    const detail =
      (body && body.detail) ||
      (typeof body === 'string' && body) ||
      `Request failed (${res.status})`;
    throw new ApiError(detail, res.status, body);
  }
  return body;
}

export const api = {
  // auth
  async login(username, password) {
    const form = new URLSearchParams({ username, password });
    const res = await fetch(`${API_BASE}/api/v1/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form,
    });
    if (!res.ok) {
      const b = await res.json().catch(() => null);
      throw new ApiError((b && b.detail) || 'Incorrect username or password', res.status, b);
    }
    const data = await res.json();
    auth.set(data.access_token, {
      id: data.user_id, username: data.username, role: data.role,
    });
    return data;
  },
  logout: () => request('/api/v1/auth/logout', { method: 'POST' }).catch(() => {}),

  // portfolio
  accounts: () => request('/api/v1/portfolio/accounts'),
  summary: (id, paper = false) =>
    request(`/api/v1/portfolio/${id}/summary?is_paper=${paper}`),
  transactions: (id, paper = false) =>
    request(`/api/v1/portfolio/${id}/transactions?is_paper=${paper}`),

  // instruments
  instruments: () => request('/api/v1/instruments/'),
  prices: (id, interval = '1min', limit = 240) =>
    request(`/api/v1/instruments/${id}/prices?interval=${interval}&limit=${limit}`),
  book: (id) => request(`/api/v1/instruments/${id}/book`),
  sentiment: (id) => request(`/api/v1/instruments/${id}/sentiment`),
  calendar: () => request('/api/v1/instruments/calendar'),

  // orders
  placeOrder: (payload) =>
    request('/api/v1/orders/', { method: 'POST', body: JSON.stringify(payload) }),
  placeCommand: (payload) =>
    request('/api/v1/orders/command', { method: 'POST', body: JSON.stringify(payload) }),
  orders: (params = '') => request(`/api/v1/orders/${params}`),
  orderAudit: (id) => request(`/api/v1/orders/${id}/audit`),
  cancelOrder: (id) => request(`/api/v1/orders/${id}/cancel`, { method: 'POST' }),

  // trades
  trades: (paper = false) => request(`/api/v1/trades/?is_paper=${paper}`),

  // exceptions
  exceptions: (params = '') => request(`/api/v1/exceptions/${params}`),
  exceptionStats: () => request('/api/v1/exceptions/stats'),
  resolveException: (id, action, reason) =>
    request(`/api/v1/exceptions/${id}/resolve`, {
      method: 'POST', body: JSON.stringify({ action, reason }),
    }),

  // risk
  limits: () => request('/api/v1/risk/limits'),
  killSwitch: () => request('/api/v1/risk/kill-switch'),
  killActivate: () => request('/api/v1/risk/kill-switch/activate', { method: 'POST' }),
  killDeactivate: () => request('/api/v1/risk/kill-switch/deactivate', { method: 'POST' }),

  // ops
  opsDashboard: () => request('/api/v1/system/dashboard'),
  settlements: () => request('/api/v1/system/settlements'),
  stpRate: () => request('/api/v1/system/stp-rate'),
};

export { ApiError };
