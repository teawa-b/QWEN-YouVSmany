# You Vs Many Frontend

Static single-page app for running and inspecting debate episodes.

Three.js is vendored at `vendor/three/` (v0.160.0, build + the addons the
player uses), so the app has no runtime CDN dependency and works offline.

## Run Locally

```bash
npm start
```

Open `http://127.0.0.1:5173`.

## Visual QA

```bash
npm run visual:qa
```

This browser check mounts the Three.js player from a scene manifest, verifies
that the premade GLB studio set loaded, checks the 9:16 crop area, and confirms
that the local realistic reference bank is served with valid media MIME types.

The browser-driven scripts (`visual:qa`, `package:episode`, `capture:refs`,
`export:mock-video`) need Playwright plus a Chromium-family browser. They try
Edge, then Playwright's managed Chromium. To use a specific system browser
(e.g. in containers/CI where Playwright's own build is not downloaded), set:

```bash
YVM_BROWSER_PATH=/path/to/chrome npm run visual:qa
```

## Package Episode

```bash
npm run package:episode -- --url=http://127.0.0.1:5173 --api=http://127.0.0.1:8000
```

This creates `output/submission/latest` with the locked episode JSON, scene
manifest, base edit, segment clips, hero stills, short candidates, and a local
review page.

## Backend API URL

By default, local/file usage calls `http://127.0.0.1:8000`.

For hosted frontend deployments, set the backend URL with one of:

```text
https://your-frontend.example.com/?api=https://your-api.example.com
```

```js
window.YVM_API_BASE = "https://your-api.example.com";
```

```js
localStorage.setItem("YVM_API_BASE", "https://your-api.example.com");
```

## Railway

Create a Railway service from the repo with:

```text
Root Directory: /frontend
Railway Config File: /frontend/railway.toml
```

Set this variable on the frontend service after the backend has a public domain:

```text
YVM_API_BASE=https://your-backend-domain.up.railway.app
```
