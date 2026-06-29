/**
 * Aquasavannah LandVault SDK — Auth client.
 * Wire-level mapping to /api/v1/auth/*.
 */
import { SdkRuntime } from './runtime';
import type {
  LoginGoogleRequest,
  LoginLocalRequest,
  RegisterRequest,
  TokenResponse,
} from './types';

export class AuthClient {
  constructor(private readonly rt: SdkRuntime) {}

  register(req: RegisterRequest): Promise<TokenResponse> {
    return this.rt.request('POST', '/api/v1/auth/register', req);
  }
  login(req: LoginLocalRequest): Promise<TokenResponse> {
    return this.rt.request('POST', '/api/v1/auth/login', req);
  }
  loginGoogle(req: LoginGoogleRequest): Promise<TokenResponse> {
    return this.rt.request('POST', '/api/v1/auth/login/google', req);
  }
  refresh(): Promise<TokenResponse> {
    return this.rt.request('POST', '/api/v1/auth/refresh');
  }
  logout(): Promise<void> {
    return this.rt.request('POST', '/api/v1/auth/logout');
  }
  me(): Promise<{ user: TokenResponse['user'] }> {
    return this.rt.request('GET', '/api/v1/auth/me');
  }
}
