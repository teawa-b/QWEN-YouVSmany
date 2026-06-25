import { createReadStream, existsSync, readFileSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { createServer } from "node:http";

const root = process.cwd();
const port = Number(process.env.PORT || 5173);

const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

function send(res, status, body, type = "text/plain; charset=utf-8") {
  res.writeHead(status, {
    "Content-Type": type,
    "Cache-Control": "no-store",
  });
  res.end(body);
}

function apiBase() {
  return process.env.YVM_API_BASE || process.env.FRONTEND_API_BASE || process.env.API_BASE || "";
}

createServer((req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

  if (url.pathname === "/health") {
    return send(res, 200, "ok");
  }

  if (url.pathname === "/config.js") {
    return send(
      res,
      200,
      `window.YVM_API_BASE = ${JSON.stringify(apiBase())};\n`,
      "application/javascript; charset=utf-8",
    );
  }

  const rawPath = url.pathname === "/" ? "index.html" : url.pathname.replace(/^\/+/, "");
  const safePath = normalize(rawPath).replace(/^(\.\.[/\\])+/, "");
  const filePath = join(root, safePath);

  if (!filePath.startsWith(root) || !existsSync(filePath)) {
    const index = readFileSync(join(root, "index.html"));
    res.writeHead(200, { "Content-Type": types[".html"] });
    return res.end(index);
  }

  res.writeHead(200, { "Content-Type": types[extname(filePath)] || "application/octet-stream" });
  createReadStream(filePath).pipe(res);
}).listen(port, "0.0.0.0", () => {
  console.log(`Frontend listening on ${port}`);
});
