import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

import { JSDOM } from "jsdom";

// Run after `npm run build`. All servers belong to this process and use local,
// ephemeral ports; the fake API refuses every request so a live check fails.
const webDir = fileURLToPath(new URL("../", import.meta.url));
const samples = JSON.parse(await readFile(path.join(webDir, "mock/samples.json"), "utf8"));
const locales = ["ru", "kk", "en", "zh"];
const apiRequests = [];
const api = createServer((request, response) => {
  apiRequests.push(`${request.method} ${request.url}`);
  request.resume();
  response.writeHead(429, { "content-type": "application/json", "retry-after": "60" });
  response.end(JSON.stringify({ error: "rate_limited", retry_after: 60 }));
});

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.removeListener("error", reject);
      resolve(server.address().port);
    });
  });
}

async function closeServer(server) {
  if (!server.listening) return;
  server.closeAllConnections();
  await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
}

let next;
let nextExit;
let stopped = false;
let serverOutput = "";

try {
  await readFile(path.join(webDir, ".next/BUILD_ID"), "utf8");
  const apiPort = await listen(api);
  // Release a temporary listener just before starting Next on that port.
  const reservation = createServer();
  const webPort = await listen(reservation);
  await closeServer(reservation);
  const origin = `http://127.0.0.1:${webPort}`;

  next = spawn(
    process.execPath,
    [path.join(webDir, "node_modules/next/dist/bin/next"), "start", "--hostname", "127.0.0.1", "--port", String(webPort)],
    {
      cwd: webDir,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...process.env,
        NODE_ENV: "production",
        NEXT_TELEMETRY_DISABLED: "1",
        SAQBOL_API_BASE: `http://127.0.0.1:${apiPort}`,
        SAQBOL_SITE_URL: origin,
        TURNSTILE_SITE_KEY: "",
        TURNSTILE_SECRET_KEY: "",
      },
    },
  );
  const collectOutput = (chunk) => {
    serverOutput = (serverOutput + chunk.toString()).slice(-16_000);
  };
  next.stdout.on("data", collectOutput);
  next.stderr.on("data", collectOutput);
  nextExit = new Promise((resolve) => {
    next.once("error", (error) => {
      collectOutput(error.message);
      stopped = true;
      resolve();
    });
    next.once("exit", () => {
      stopped = true;
      resolve();
    });
  });

  const deadline = Date.now() + 45_000;
  let ready = false;
  while (Date.now() < deadline && !stopped) {
    try {
      const response = await fetch(`${origin}/en`, { signal: AbortSignal.timeout(1_000) });
      await response.text();
      if (response.ok) {
        ready = true;
        break;
      }
    } catch {
      // Connection refusal is expected while Next starts listening.
    }
    await delay(150);
  }
  assert.ok(ready, "Built Next server did not become ready within 45 seconds.");

  async function inspect(locale, sample) {
    const ui = JSON.parse(await readFile(path.join(webDir, `i18n/ui.${locale}.json`), "utf8"));
    const id = sample?.id ?? "not-a-real-sample";
    const route = `/${locale}?sample=${encodeURIComponent(id)}`;
    const response = await fetch(`${origin}${route}`, { signal: AbortSignal.timeout(15_000) });
    assert.equal(response.status, 200, route);
    const dom = new JSDOM(await response.text());
    try {
      const document = dom.window.document;
      assert.equal(document.documentElement.lang.split("-")[0], locale, route);
      assert.equal(document.querySelector('textarea[name="text"]')?.value, sample?.text ?? "", route);
      const card = document.querySelector('section[aria-labelledby="verdict-title"]');
      const labels = [...document.querySelectorAll("p")].map((paragraph) => paragraph.textContent.trim());
      if (sample) {
        assert.ok(card?.querySelector("#verdict-title"), `Missing sample verdict: ${route}`);
        assert.equal(card.dataset.band, sample.band, route);
        assert.equal(card.previousElementSibling?.textContent.trim(), ui["form.samples.result"], route);
      } else {
        assert.equal(card, null, route);
        assert.ok(!labels.includes(ui["form.samples.result"]), route);
      }
      assert.ok(!labels.includes(ui["mock.banner"]), `API configuration was ignored: ${route}`);
      assert.deepEqual(apiRequests, [], `Sample navigation called the API: ${route}`);
    } finally {
      dom.window.close();
    }
  }

  for (const locale of locales) {
    for (const sample of samples) await inspect(locale, sample);
    await inspect(locale, null);
    console.log(`Sample smoke: ${locale}, ${samples.length} examples and invalid sample passed.`);
  }
  assert.deepEqual(apiRequests, []);
  console.log(`Passed ${samples.length * locales.length} sample pages and ${locales.length} invalid samples; no API requests.`);
} catch (error) {
  if (serverOutput) console.error(serverOutput);
  throw error;
} finally {
  if (next && !stopped) {
    next.kill("SIGTERM");
    await Promise.race([nextExit, delay(3_000)]);
    if (!stopped) {
      next.kill("SIGKILL");
      await Promise.race([nextExit, delay(3_000)]);
    }
  }
  await closeServer(api);
}
