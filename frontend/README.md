# You Vs Many Frontend

Static single-page app for running and inspecting debate episodes.

## Run Locally

```bash
python -m http.server 5173
```

Open `http://127.0.0.1:5173`.

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
