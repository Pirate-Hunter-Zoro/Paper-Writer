// Check the driver's selectors against the REAL gemini.google.com, right now.
//
// `tests/test_browser_driver.py` proves everything about the driver except the one
// thing that actually breaks: whether the selectors still match Google's markup. A
// fixture I wrote will always agree with selectors I wrote. This asks the real page.
//
//   node tools/probe_selectors.js            signed-out (guest) -- no account needed
//   node tools/probe_selectors.js --send     also sends a prompt and watches the reply
//
// A GUEST SESSION IS ENOUGH FOR MOST OF IT, which is the useful part: gemini.google.com
// serves signed-out visitors a real composer, a real send button, a real response
// container and a real stop-generating control. Four of the six selector groups can
// therefore be verified against the live app by anyone, with no credentials.
//
// The two it cannot reach are the two that need an account: the file input behind the
// upload menu, and a generated image. Those stay unverified until somebody signs in and
// runs `scripts/check-browser.sh --live`, and this script says so rather than implying
// a clean run means the driver works.

import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";

const CHROME = process.env.CHROME_BIN ||
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PROFILE = process.env.GEMINI_PROFILE_DIR ||
  join(homedir(), ".config", "fanfic", "chrome-gemini");
const URL_ = process.env.GEMINI_ART_URL || "https://gemini.google.com/app";
const SEND = process.argv.includes("--send");

// The selector groups exactly as `gemini_art.js` uses them. Kept as literal strings
// rather than imported, because the point is to catch the two drifting apart.
const GROUPS = [
  { key: "composer", needs: "guest",
    why: "where the prompt is typed",
    sel: 'rich-textarea div[contenteditable="true"], div.ql-editor[contenteditable="true"], div[contenteditable="true"][role="textbox"], textarea[aria-label]' },
  { key: "send", needs: "guest",
    why: "submits the prompt (Enter is the fallback)",
    sel: 'button[aria-label*="Send" i], button.send-button, [data-test-id="send-button"]' },
  { key: "account", needs: "signed-in",
    why: "proves a session exists; a composer alone does NOT",
    sel: 'a[aria-label*="Google Account" i], a[href*="myaccount.google.com"], [data-test-id="account-menu"], img[alt*="Account" i]' },
  { key: "signin-cta", needs: "guest",
    why: "the negative signal for the same question",
    sel: 'a[href*="ServiceLogin"], a[href*="accounts.google.com"]' },
  { key: "response", needs: "after a send",
    why: "scopes the search for the picture to the newest reply",
    sel: 'model-response, message-content, [data-test-id="model-response"]' },
  { key: "busy", needs: "during generation",
    why: "stops us saving a half-drawn image",
    sel: 'button[aria-label*="Stop" i], button[aria-label*="stop response" i], .stop-icon, [data-test-id="stop-button"]' },
  { key: "file-input", needs: "signed-in",
    why: "uploads the locked reference sheets -- visual consistency depends on it",
    sel: 'input[type="file"]' },
  { key: "upload-menu", needs: "signed-in",
    why: "clicked only if the file input is not already in the DOM",
    sel: 'button[aria-label*="upload" i], button[aria-label*="add file" i], button[aria-label*="Open upload" i], button[aria-label*="attach" i], uploader button, button.upload-card-button' },
];

async function getJson(url) { return (await fetch(url)).json(); }

async function waitFor(fn, timeoutMs, intervalMs = 500) {
  const t0 = Date.now();
  for (;;) {
    const v = await fn();
    if (v) return v;
    if (Date.now() - t0 > timeoutMs) return null;
    await sleep(intervalMs);
  }
}

class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); }
  static async connect(url) {
    const ws = new WebSocket(url);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    const c = new CDP(ws);
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && c.pending.has(m.id)) {
        const { resolve: ok, reject: no } = c.pending.get(m.id);
        c.pending.delete(m.id);
        m.error ? no(new Error(JSON.stringify(m.error))) : ok(m.result);
      }
    };
    return c;
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((ok, no) => {
      this.pending.set(id, { resolve: ok, reject: no });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expr) {
    const r = await this.send("Runtime.evaluate",
                              { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text || "eval failed");
    return r.result?.value;
  }
}

// For each group: how many nodes match, and enough about the first to recognise drift.
function probeExpr(groups) {
  return `(() => {
    const out = {};
    const groups = ${JSON.stringify(groups.map((g) => [g.key, g.sel]))};
    for (const [key, sel] of groups) {
      let nodes = [];
      try { nodes = [...document.querySelectorAll(sel)]; } catch (e) {
        out[key] = { error: e.message }; continue;
      }
      const first = nodes[0];
      out[key] = {
        count: nodes.length,
        tag: first ? first.tagName.toLowerCase() : null,
        aria: first ? (first.getAttribute('aria-label') || '') : '',
        cls: first ? (first.getAttribute('class') || '').slice(0, 70) : '',
        // Which arm of the selector list matched, so a group that survives only on its
        // last fallback is visible BEFORE the others rot away entirely.
        arm: (() => {
          if (!first) return null;
          for (const one of sel.split(',').map((s) => s.trim())) {
            try { if (first.matches(one)) return one; } catch (e) { /* skip */ }
          }
          return '(no single arm matched)';
        })(),
      };
    }
    return JSON.stringify(out);
  })()`;
}

async function main() {
  mkdirSync(PROFILE, { recursive: true });
  const port = 9900 + Math.floor(Math.random() * 90);
  const chrome = spawn(CHROME, [
    "--headless=new", "--no-first-run", "--no-default-browser-check", "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--window-size=1400,1100",
    `--user-data-dir=${PROFILE}`, `--remote-debugging-port=${port}`, URL_,
  ], { stdio: "ignore" });

  try {
    const version = await waitFor(async () => {
      try { return await getJson(`http://127.0.0.1:${port}/json/version`); }
      catch { return null; }
    }, 25000);
    if (!version) throw new Error(`devtools never came up on ${port}`);

    const targets = await getJson(`http://127.0.0.1:${port}/json/list`);
    const page = targets.find((t) => t.type === "page");
    const cdp = await CDP.connect(page.webSocketDebuggerUrl);
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");

    // Give the app time to hydrate; a probe against an empty shell proves nothing.
    await waitFor(async () => {
      const n = await cdp.eval(
        `document.querySelectorAll('rich-textarea, div[contenteditable="true"], textarea').length`);
      return n > 0 ? n : null;
    }, 45000, 1000);
    await sleep(1500);

    // TYPE BEFORE PROBING. Several controls only render once the composer has content
    // -- the send button most of all. The first version of this script probed an empty
    // composer and reported `send` MISSING against an app where it was perfectly fine,
    // which is a false alarm about the one thing this script exists to detect. A probe
    // that cries wolf gets ignored, so it now puts the page in the state the driver
    // actually puts it in before asking what is there.
    await cdp.eval(`(() => {
      const el = document.querySelector(${JSON.stringify(GROUPS[0].sel)});
      if (el) { el.focus(); el.click(); }
      return !!el;
    })()`);
    await cdp.send("Input.insertText", { text: "probe" });
    await sleep(1200);

    console.log(`\nProbing ${await cdp.eval("location.href")}`);
    console.log(`Chrome ${version.Browser}\n`);

    let report = JSON.parse(await cdp.eval(probeExpr(GROUPS)));
    render(report, false);

    if (SEND) {
      console.log("\n--- sending a prompt, to reach the response-side selectors ---\n");
      await cdp.eval(`(() => {
        const el = document.querySelector(${JSON.stringify(GROUPS[0].sel)});
        if (el) { el.focus(); el.click(); }
        return !!el;
      })()`);
      await cdp.eval(`(() => {
        const el = document.querySelector(${JSON.stringify(GROUPS[0].sel)});
        if (el) { el.focus(); el.click();
                  document.execCommand && document.execCommand('selectAll', false, null); }
        return !!el;
      })()`);
      await cdp.send("Input.insertText", { text: "Say the single word: acknowledged." });
      await sleep(600);
      const clicked = await cdp.eval(`(() => {
        const b = document.querySelector(${JSON.stringify(GROUPS[1].sel)});
        if (b && !b.disabled) { b.click(); return true; }
        return false;
      })()`);
      if (!clicked) {
        for (const type of ["keyDown", "keyUp"]) {
          await cdp.send("Input.dispatchKeyEvent",
            { type, key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
        }
      }
      console.log(clicked ? "sent via the send button" : "sent via Enter (no send button matched)");
      // Remember it MATCHED, because by the time the groups are probed it will not.
      // The send control only exists while the composer has content, and this path
      // deliberately empties the composer before it measures anything. Reporting the
      // group from that snapshot printed `send MISSING` on every --send run, against
      // an app where the button had just been found and clicked one line earlier —
      // which is the exact false alarm the comment above `TYPE BEFORE PROBING` says
      // this script was fixed once to avoid. Same shape as `sawBusy` below: a control
      // that is only alive for part of the flow has to be recorded when it is alive.
      const sawSend = clicked;

      // Catch `busy` while it is up: it only exists during generation.
      let sawBusy = false;
      await waitFor(async () => {
        if (await cdp.eval(`!!document.querySelector(${JSON.stringify(GROUPS[5].sel)})`)) {
          sawBusy = true;
        }
        const text = await cdp.eval(
          `(() => { const s = document.querySelectorAll('model-response, message-content');
             return s.length ? (s[s.length-1].innerText||'').trim() : ''; })()`);
        return text.length > 3 ? text : null;
      }, 60000, 400);

      report = JSON.parse(await cdp.eval(probeExpr(GROUPS)));
      render(report, sawBusy, sawSend);

      const reply = await cdp.eval(
        `(() => { const s = document.querySelectorAll('model-response, message-content');
           return s.length ? (s[s.length-1].innerText||'').slice(0,200) : '(none)'; })()`);
      console.log(`\nreply text seen: ${JSON.stringify(reply)}`);
    }

    cdp.ws.close();
  } finally {
    chrome.kill("SIGKILL");
  }
}

function render(report, sawBusy, sawSend) {
  const pad = (s, n) => String(s).padEnd(n);
  console.log(pad("GROUP", 14) + pad("STATUS", 10) + pad("N", 4) + "MATCHED ARM");
  console.log("-".repeat(96));
  for (const g of GROUPS) {
    const r = report[g.key] || {};
    const found = (r.count || 0) > 0
                  || (g.key === "busy" && sawBusy)
                  || (g.key === "send" && sawSend);
    let status;
    if (found) status = "OK";
    else if (g.needs === "signed-in") status = "n/a";
    else if (g.needs === "during generation" || g.needs === "after a send") status = "n/a";
    else status = "MISSING";
    console.log(pad(g.key, 14) + pad(status, 10) + pad(r.count ?? 0, 4) +
                (r.arm || (status === "n/a" ? `(needs ${g.needs})` : "-")));
  }
  console.log("-".repeat(96));
  console.log("OK = this selector still matches the live app.");
  console.log("n/a = not reachable in this mode; NOT a pass. See --send and check-browser.sh --live.");
}

main().catch((e) => { console.error("probe failed:", e.message); process.exit(1); });
