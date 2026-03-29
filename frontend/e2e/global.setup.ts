import { request, type FullConfig } from '@playwright/test';
import { E2E_BEARER_TOKEN, authHeaders } from './auth';

export default async function globalSetup(config: FullConfig): Promise<void> {
  const configuredBaseURL = config.projects[0]?.use?.baseURL;
  const baseURL =
    (typeof configuredBaseURL === 'string' && configuredBaseURL.trim()) ||
    process.env.PLAYWRIGHT_BASE_URL?.trim() ||
    'http://127.0.0.1';

  const api = await request.newContext({
    baseURL,
    extraHTTPHeaders: E2E_BEARER_TOKEN ? authHeaders() : undefined,
  });

  try {
    const health = await api.get('/api/health');
    if (!health.ok()) {
      throw new Error(`Playwright global setup could not reach ${baseURL}/api/health`);
    }

    if (E2E_BEARER_TOKEN) {
      const me = await api.get('/api/users/me');
      if (!me.ok()) {
        throw new Error(`Playwright global setup could not validate bearer token: ${me.status()}`);
      }
    }
  } finally {
    await api.dispose();
  }
}
