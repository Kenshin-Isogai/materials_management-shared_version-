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
```

### Production Build

```bash
npm run build
```

The production deployment is baked into the nginx container defined in `frontend/Dockerfile`.

