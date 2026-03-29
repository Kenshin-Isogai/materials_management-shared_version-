import { request, type FullConfig } from '@playwright/test';

type UserRecord = {
  username?: string;
};

function extractUsers(payload: unknown): UserRecord[] {
  if (Array.isArray(payload)) {
    return payload as UserRecord[];
  }
  if (payload && typeof payload === 'object' && Array.isArray((payload as { data?: unknown }).data)) {
    return (payload as { data: UserRecord[] }).data;
  }
  return [];
}

export default async function globalSetup(config: FullConfig): Promise<void> {
  const configuredBaseURL = config.projects[0]?.use?.baseURL;
  const baseURL =
    (typeof configuredBaseURL === 'string' && configuredBaseURL.trim()) ||
    process.env.PLAYWRIGHT_BASE_URL?.trim() ||
    'http://127.0.0.1';

  const api = await request.newContext({ baseURL });

  try {
    const health = await api.get('/api/health');
    if (!health.ok()) {
      throw new Error(`Playwright global setup could not reach ${baseURL}/api/health`);
    }

    const usersResponse = await api.get('/api/users?include_inactive=false');
    if (!usersResponse.ok()) {
      throw new Error(`Playwright global setup could not list users: ${usersResponse.status()}`);
    }

    const usersPayload = await usersResponse.json();
    const users = extractUsers(usersPayload);
    if (users.some((user) => user.username === 'e2e.admin')) {
      return;
    }

    const createResponse = await api.post('/api/users', {
      data: {
        username: 'e2e.admin',
        display_name: 'E2E Admin',
        role: 'admin',
        is_active: true,
      },
    });
    if (!createResponse.ok()) {
      throw new Error(`Playwright global setup could not create bootstrap user: ${createResponse.status()}`);
    }
  } finally {
    await api.dispose();
  }
}
