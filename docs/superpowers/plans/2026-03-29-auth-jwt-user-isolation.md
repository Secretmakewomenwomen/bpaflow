# Auth JWT User Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build username/password registration and login with JWT protection so only authenticated users can enter the canvas, and ensure upload/work data is isolated by per-user `user_id` UUID.

**Architecture:** Add a small auth layer on both frontend and backend. The backend becomes the source of truth for current-user resolution by extracting `user_id` from JWT and applying it to every protected business route. The frontend becomes route-driven with a public auth page, a protected canvas page, and a shared HTTP wrapper that automatically attaches the token.

**Tech Stack:** Vue 3, TypeScript, Rsbuild, vue-router, ant-design-vue, FastAPI, SQLAlchemy, Pydantic, JWT, password hashing, pytest

---

### Task 1: Add Frontend Dependencies And Routing Shell

**Files:**
- Modify: `package.json`
- Modify: `src/main.ts`
- Modify: `src/App.vue`
- Create: `src/router/index.ts`
- Create: `src/pages/AuthPage.vue`
- Create: `src/pages/CanvasPage.vue`

- [ ] **Step 1: Write the failing route-level expectation**

Document the expected behavior before implementation:

```ts
// routing expectation
// unauthenticated => /canvas redirects to /login
// authenticated => /login redirects to /canvas
```

- [ ] **Step 2: Add the missing frontend packages**

Update `package.json` dependencies to include:

```json
{
  "dependencies": {
    "ant-design-vue": "latest-compatible",
    "vue-router": "latest-compatible"
  }
}
```

- [ ] **Step 3: Install dependencies**

Run: `pnpm install`
Expected: lockfile updates with `ant-design-vue` and `vue-router`

- [ ] **Step 4: Create the router entry**

Create `src/router/index.ts` with:

```ts
import { createRouter, createWebHistory } from 'vue-router';
import AuthPage from '../pages/AuthPage.vue';
import CanvasPage from '../pages/CanvasPage.vue';
import { hasToken, restoreAuthState } from '../lib/auth';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/canvas' },
    { path: '/login', component: AuthPage, meta: { public: true } },
    { path: '/canvas', component: CanvasPage }
  ]
});

router.beforeEach(async (to) => {
  if (hasToken()) {
    await restoreAuthState();
  }

  if (!to.meta.public && !hasToken()) {
    return '/login';
  }

  if (to.path === '/login' && hasToken()) {
    return '/canvas';
  }

  return true;
});

export default router;
```

- [ ] **Step 5: Mount router and Ant Design**

Update `src/main.ts` to:

```ts
import { createApp } from 'vue';
import Antd from 'ant-design-vue';
import 'ant-design-vue/dist/reset.css';
import App from './App.vue';
import router from './router';

createApp(App).use(router).use(Antd).mount('#root');
```

- [ ] **Step 6: Replace `src/App.vue` with a route outlet**

Use the minimal shell:

```vue
<template>
  <RouterView />
</template>
```

- [ ] **Step 7: Create placeholder `AuthPage.vue` and `CanvasPage.vue`**

Expected placeholders:

```vue
<template><div>auth page</div></template>
```

```vue
<template><div>canvas page</div></template>
```

- [ ] **Step 8: Run a frontend build smoke test**

Run: `pnpm build`
Expected: build succeeds or fails only because auth modules are not implemented yet

- [ ] **Step 9: Commit**

```bash
git add package.json pnpm-lock.yaml src/main.ts src/App.vue src/router/index.ts src/pages/AuthPage.vue src/pages/CanvasPage.vue
git commit -m "feat: add auth routing shell"
```

### Task 2: Implement Frontend Auth State, Forms, And Protected Canvas Page

**Files:**
- Create: `src/lib/auth.ts`
- Create: `src/lib/http.ts`
- Create: `src/types/auth.ts`
- Modify: `src/pages/AuthPage.vue`
- Modify: `src/pages/CanvasPage.vue`
- Modify: `src/components/AppHeader.vue`
- Modify: `src/lib/upload.ts`

- [ ] **Step 1: Write the failing auth behavior expectations**

Document the target behaviors:

```ts
// register success stores token and user
// login success stores token and user
// logout clears token and redirects
// protected API requests attach Authorization header
```

- [ ] **Step 2: Define auth types**

Create `src/types/auth.ts`:

```ts
export interface AuthUser {
  user_id: string;
  username: string;
}

export interface AuthSuccessResponse {
  access_token: string;
  token_type: 'bearer';
  user: AuthUser;
}
```

- [ ] **Step 3: Add shared auth storage helpers**

Create `src/lib/auth.ts` with:

```ts
const TOKEN_KEY = 'auth_token';
const USER_KEY = 'auth_user';

export function getToken() { /* localStorage read */ }
export function hasToken() { /* boolean */ }
export function saveAuth(payload) { /* save token + user */ }
export function clearAuth() { /* remove both */ }
export async function restoreAuthState() { /* call /api/auth/me when token exists */ }
```

- [ ] **Step 4: Add HTTP wrapper**

Create `src/lib/http.ts`:

```ts
import { getToken, clearAuth } from './auth';

export async function apiFetch(path: string, init: RequestInit = {}) {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (!headers.has('Content-Type') && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) clearAuth();
  return response;
}
```

- [ ] **Step 5: Build the Ant Design auth page**

Implement `src/pages/AuthPage.vue` with:

- `Tabs` for login/register
- `Form`, `Input`, `InputPassword`, `Button`, `Alert`
- register form with confirm-password validation
- submit handlers that call `/api/auth/register` and `/api/auth/login`
- success path: `saveAuth(...)` then `router.push('/canvas')`

- [ ] **Step 6: Extract the existing workbench into `CanvasPage.vue`**

Move the current `src/App.vue` canvas logic and template into `src/pages/CanvasPage.vue`, then:

- inject current user display
- add logout button
- redirect to `/login` after logout

- [ ] **Step 7: Update header props for user display and logout**

Extend `src/components/AppHeader.vue` to accept:

```ts
user?: { username: string } | null
```

and emit:

```ts
'logout'
```

- [ ] **Step 8: Migrate upload requests to shared HTTP wrapper**

Update `src/lib/upload.ts` to replace raw `fetch(...)` with `apiFetch(...)`.

- [ ] **Step 9: Run the frontend build**

Run: `pnpm build`
Expected: app builds with auth page and protected canvas route

- [ ] **Step 10: Commit**

```bash
git add src/lib/auth.ts src/lib/http.ts src/types/auth.ts src/pages/AuthPage.vue src/pages/CanvasPage.vue src/components/AppHeader.vue src/lib/upload.ts
git commit -m "feat: add frontend auth flow"
```

### Task 3: Add Backend User Model, Password Hashing, And JWT Auth Routes

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/main.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/core/database.py`
- Create: `backend/app/models/user.py`
- Create: `backend/app/schemas/auth.py`
- Create: `backend/app/core/security.py`
- Create: `backend/app/api/routes/auth.py`

- [ ] **Step 1: Write the failing auth API tests**

Create tests in `backend/tests/test_auth_api.py`:

```python
def test_register_returns_token_and_user(client): ...
def test_duplicate_username_is_rejected(client): ...
def test_login_returns_token_and_user(client): ...
def test_wrong_password_is_rejected(client): ...
def test_me_returns_current_user(client): ...
```

- [ ] **Step 2: Run the auth tests to verify failure**

Run: `pytest backend/tests/test_auth_api.py -v`
Expected: FAIL because auth routes and models do not exist

- [ ] **Step 3: Add backend auth dependencies**

Update `backend/requirements.txt` with compatible packages for:

- JWT encode/decode
- password hashing
- form/security helpers if needed

- [ ] **Step 4: Create the user model**

Create `backend/app/models/user.py` with:

```python
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(36), unique=True, nullable=False, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
```

- [ ] **Step 5: Register the user model and schema creation**

Ensure the user table is created from existing startup/bootstrap flow in `backend/app/core/database.py` and `backend/app/main.py`.

- [ ] **Step 6: Add auth schemas**

Create `backend/app/schemas/auth.py` with:

```python
class RegisterRequest(BaseModel): ...
class LoginRequest(BaseModel): ...
class CurrentUserResponse(BaseModel): ...
class AuthResponse(BaseModel): ...
```

- [ ] **Step 7: Add password and JWT helpers**

Create `backend/app/core/security.py` with functions:

```python
def hash_password(password: str) -> str: ...
def verify_password(password: str, password_hash: str) -> bool: ...
def create_access_token(user_id: str, username: str) -> str: ...
def decode_access_token(token: str) -> dict: ...
```

- [ ] **Step 8: Add auth routes**

Create `backend/app/api/routes/auth.py` for:

- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`

Implementation rules:

- generate UUID for `user_id`
- reject duplicate usernames
- return `{ access_token, token_type, user }`

- [ ] **Step 9: Register the auth router**

Update `backend/app/main.py` to include:

```python
app.include_router(auth_router, prefix="/api")
```

- [ ] **Step 10: Run auth tests**

Run: `pytest backend/tests/test_auth_api.py -v`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add backend/requirements.txt backend/app/main.py backend/app/models/__init__.py backend/app/core/database.py backend/app/models/user.py backend/app/schemas/auth.py backend/app/core/security.py backend/app/api/routes/auth.py backend/tests/test_auth_api.py
git commit -m "feat: add backend auth api"
```

### Task 4: Add Current-User Dependency And Isolate Upload Data By `user_id`

**Files:**
- Create: `backend/app/dependencies/auth.py`
- Modify: `backend/app/models/upload.py`
- Modify: `backend/app/schemas/upload.py`
- Modify: `backend/app/api/routes/uploads.py`
- Modify: `backend/app/services/upload_service.py`
- Modify: `backend/tests/test_upload_api.py`
- Modify: `backend/tests/test_upload_service.py`

- [ ] **Step 1: Write the failing upload isolation tests**

Add tests covering:

```python
def test_upload_list_only_returns_current_users_records(client): ...
def test_delete_other_users_upload_returns_404(client): ...
def test_upload_endpoint_requires_auth(client): ...
```

- [ ] **Step 2: Run only the upload isolation tests**

Run: `pytest backend/tests/test_upload_api.py -v`
Expected: FAIL because auth dependency and `user_id` filtering do not exist

- [ ] **Step 3: Add shared current-user dependency**

Create `backend/app/dependencies/auth.py`:

```python
oauth2_scheme = HTTPBearer(auto_error=False)

def get_current_user(...):
    # read bearer token
    # decode JWT
    # load user by user_id
    # raise 401 if invalid
```

- [ ] **Step 4: Add `user_id` to upload model**

Update `backend/app/models/upload.py`:

```python
user_id = Column(String(36), nullable=False, index=True)
```

- [ ] **Step 5: Keep upload schemas server-owned for `user_id`**

Ensure request schemas do not accept `user_id` from the frontend and response schemas only expose it if needed for debugging. Default recommendation: do not expose it.

- [ ] **Step 6: Apply auth dependency and filtering in upload routes**

Update `backend/app/api/routes/uploads.py` so every handler receives `current_user = Depends(get_current_user)` and:

- create writes `user_id=current_user.user_id`
- list filters by `current_user.user_id`
- delete filters by `current_user.user_id`

- [ ] **Step 7: Update upload service queries**

Update `backend/app/services/upload_service.py` to accept `user_id` arguments where data access occurs.

- [ ] **Step 8: Run upload tests**

Run: `pytest backend/tests/test_upload_api.py backend/tests/test_upload_service.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/dependencies/auth.py backend/app/models/upload.py backend/app/schemas/upload.py backend/app/api/routes/uploads.py backend/app/services/upload_service.py backend/tests/test_upload_api.py backend/tests/test_upload_service.py
git commit -m "feat: isolate upload data by user"
```

### Task 5: Isolate Work Data By `user_id`

**Files:**
- Modify: `backend/app/models/work.py`
- Modify: `backend/app/schemas/work.py`
- Modify: `backend/app/api/routes/work.py`
- Modify: `backend/app/services/work_service.py`
- Modify: `backend/tests/test_work_api.py`
- Modify: `backend/tests/test_work_service.py`

- [ ] **Step 1: Write the failing work isolation tests**

Add tests covering:

```python
def test_work_list_only_returns_current_users_records(client): ...
def test_delete_other_users_work_returns_404(client): ...
def test_work_endpoint_requires_auth(client): ...
```

- [ ] **Step 2: Run only the work isolation tests**

Run: `pytest backend/tests/test_work_api.py -v`
Expected: FAIL because `user_id` filtering does not exist

- [ ] **Step 3: Add `user_id` to work model**

Update `backend/app/models/work.py`:

```python
user_id = Column(String(36), nullable=False, index=True)
```

- [ ] **Step 4: Keep work creation server-owned**

Ensure create request schemas do not accept a client-provided `user_id`.

- [ ] **Step 5: Apply current-user filtering in work routes and services**

Update `backend/app/api/routes/work.py` and `backend/app/services/work_service.py` so:

- create writes current `user_id`
- list returns only current user's rows
- delete only affects current user's rows

- [ ] **Step 6: Run work tests**

Run: `pytest backend/tests/test_work_api.py backend/tests/test_work_service.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/work.py backend/app/schemas/work.py backend/app/api/routes/work.py backend/app/services/work_service.py backend/tests/test_work_api.py backend/tests/test_work_service.py
git commit -m "feat: isolate work data by user"
```

### Task 6: Verify End-To-End Behavior And Document Gaps

**Files:**
- Modify: `docs/deploy.md`
- Modify: `docs/superpowers/specs/2026-03-29-auth-jwt-user-isolation-design.md`

- [ ] **Step 1: Run focused backend auth and isolation tests**

Run:

```bash
pytest backend/tests/test_auth_api.py backend/tests/test_upload_api.py backend/tests/test_work_api.py -v
```

Expected: PASS

- [ ] **Step 2: Run the existing frontend build**

Run:

```bash
pnpm build
```

Expected: PASS

- [ ] **Step 3: Run the broader backend test suite if stable**

Run:

```bash
pytest backend/tests -v
```

Expected: PASS, or note unrelated pre-existing failures

- [ ] **Step 4: Update deployment documentation**

Add required backend env configuration for:

- JWT secret
- JWT expiration
- password hashing dependency notes

- [ ] **Step 5: Record any migration caveats**

If existing local tables require backfill or reset because of new non-null `user_id` columns, document the exact reset or migration step.

- [ ] **Step 6: Commit**

```bash
git add docs/deploy.md docs/superpowers/specs/2026-03-29-auth-jwt-user-isolation-design.md
git commit -m "docs: document auth rollout"
```
