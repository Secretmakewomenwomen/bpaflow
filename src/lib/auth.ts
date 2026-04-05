import { reactive } from 'vue';
import type { AuthSuccessResponse, AuthUser } from '../types/auth';

const TOKEN_KEY = 'auth_token';
const USER_KEY = 'auth_user';
const authApiBase = '/api/auth';

function getStorage() {
  if (typeof window === 'undefined') {
    return null;
  }

  return window.localStorage;
}

function readStoredToken() {
  return getStorage()?.getItem(TOKEN_KEY) ?? null;
}

function readStoredUser() {
  const storage = getStorage();
  const raw = storage?.getItem(USER_KEY);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    storage?.removeItem(USER_KEY);
    return null;
  }
}

export const authState = reactive<{
  token: string | null;
  user: AuthUser | null;
}>({
  token: readStoredToken(),
  user: readStoredUser()
});

export function getToken() {
  return authState.token;
}

export function hasToken() {
  return Boolean(authState.token);
}

export function getCurrentUser() {
  return authState.user;
}

export function saveAuth(payload: AuthSuccessResponse) {
  const storage = getStorage();
  authState.token = payload.access_token;
  authState.user = payload.user;
  storage?.setItem(TOKEN_KEY, payload.access_token);
  storage?.setItem(USER_KEY, JSON.stringify(payload.user));
}

export function clearAuth() {
  const storage = getStorage();
  authState.token = null;
  authState.user = null;
  storage?.removeItem(TOKEN_KEY);
  storage?.removeItem(USER_KEY);
}

async function parseAuthResponse(response: Response) {
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(payload?.detail ?? '登录失败。');
  }
  return payload as AuthSuccessResponse;
}

export async function login(username: string, password: string) {
  const response = await fetch(`${authApiBase}/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ username, password })
  });
  const payload = await parseAuthResponse(response);
  saveAuth(payload);
  return payload.user;
}

export async function register(username: string, password: string) {
  const response = await fetch(`${authApiBase}/register`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ username, password })
  });
  const payload = await parseAuthResponse(response);
  saveAuth(payload);
  return payload.user;
}

let restorePromise: Promise<AuthUser | null> | null = null;

export async function restoreAuthState() {
  if (!authState.token) {
    return null;
  }

  if (restorePromise) {
    return restorePromise;
  }

  restorePromise = (async () => {
    const response = await fetch(`${authApiBase}/me`, {
      headers: {
        Authorization: `Bearer ${authState.token}`
      }
    });

    if (!response.ok) {
      clearAuth();
      return null;
    }

    const user = (await response.json()) as AuthUser;
    authState.user = user;
    getStorage()?.setItem(USER_KEY, JSON.stringify(user));
    return user;
  })();

  try {
    return await restorePromise;
  } finally {
    restorePromise = null;
  }
}
