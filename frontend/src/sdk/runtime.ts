/**
 * Aquasavannah LandVault SDK — runtime
 *
 * Single source-of-truth HTTP layer. The React app MUST NOT make
 * fetch/axios calls outside this module. Every domain client extends
 * the SdkRuntime via composition.
 *
 * Pinned to contract v1.5.0 (Phase 3.9 SDK regeneration).
 *
 * Constitutional rules (Phase 3.9):
 *  * No business logic — wire-level only.
 *  * No hashing, no authorization, no domain rules.
 *  * Method signatures derive 1:1 from the frozen OpenAPI.
 */

export interface RuntimeOptions {
  /** Base URL — typically REACT_APP_BACKEND_URL. */
  baseUrl: string;
  /** Async function that returns the current bearer token, or null. */
  tokenProvider?: () => string | null;
  /** Send cookies cross-origin (refresh-cookie support). */
  withCredentials?: boolean;
  /** Optional fetch override (tests). */
  fetchImpl?: typeof fetch;
}

export class SdkError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly correlationId?: string;
  readonly problem: Record<string, unknown>;
  constructor(status: number, problem: Record<string, unknown>) {
    super(
      typeof problem.detail === 'string'
        ? problem.detail
        : `HTTP ${status}`
    );
    this.status = status;
    this.code = typeof problem.code === 'string' ? problem.code : 'sdk.error';
    this.detail = typeof problem.detail === 'string' ? problem.detail : '';
    this.correlationId =
      typeof problem.correlation_id === 'string'
        ? problem.correlation_id
        : undefined;
    this.problem = problem;
  }
}

export class SdkRuntime {
  readonly baseUrl: string;
  private readonly tokenProvider: () => string | null;
  private readonly withCredentials: boolean;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: RuntimeOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, '');
    this.tokenProvider = opts.tokenProvider ?? (() => null);
    this.withCredentials = opts.withCredentials ?? true;
    this.fetchImpl =
      opts.fetchImpl ??
      (typeof fetch !== 'undefined'
        ? fetch.bind(globalThis)
        : ((() => {
            throw new Error('no fetch available');
          }) as typeof fetch));
  }

  async request<T>(
    method: string,
    path: string,
    body?: unknown,
    headers?: Record<string, string>,
    raw?: boolean
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const h: Record<string, string> = {
      Accept: 'application/json',
      ...headers,
    };
    const token = this.tokenProvider();
    if (token) h.Authorization = `Bearer ${token}`;

    let payload: BodyInit | undefined;
    if (body !== undefined && !raw) {
      h['Content-Type'] = 'application/json';
      payload = JSON.stringify(body);
    } else if (raw && body !== undefined) {
      payload = body as BodyInit;
    }

    const res = await this.fetchImpl(url, {
      method,
      headers: h,
      body: payload,
      credentials: this.withCredentials ? 'include' : 'same-origin',
    });

    if (res.status === 204) return undefined as unknown as T;
    const ct = res.headers.get('content-type') || '';
    if (!res.ok) {
      let problem: Record<string, unknown> = {
        title: res.statusText,
        status: res.status,
      };
      if (ct.includes('application/json') || ct.includes('problem+json')) {
        try {
          problem = await res.json();
        } catch {
          /* keep default */
        }
      }
      throw new SdkError(res.status, problem);
    }
    if (ct.includes('application/json')) return (await res.json()) as T;
    return (await res.text()) as unknown as T;
  }
}
