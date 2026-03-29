## Optical Component Inventory Management Frontend

### Setup

```bash
npm install
```

### Start Development Server

```bash
npm run dev
```

Default URL: `http://127.0.0.1:5173`

### Environment

Set backend URL if needed:

```bash
VITE_API_BASE=http://127.0.0.1:8000/api
VITE_GOOGLE_CLIENT_ID=<google-oauth-client-id>
```

- `VITE_GOOGLE_CLIENT_ID` enables the Google Identity sign-in button in the shared header.
- If it is unset, the header falls back to manual Bearer token entry only.

### Production Build

```bash
npm run build
```

The production deployment is baked into the nginx container defined in `frontend/Dockerfile`.

- The built image uses `frontend/nginx.conf`, which is cloud-first and does not proxy `/api` to a backend container.
- Local Docker Compose keeps same-origin `/api` behavior by mounting `frontend/nginx.local-proxy.conf` into the nginx container.
- For split-service Cloud Run deployment, build with `VITE_API_BASE=https://<backend-service-url>/api`.
- For Google Identity browser sign-in, also build with `VITE_GOOGLE_CLIENT_ID=<google-oauth-client-id>`.

