// Ask Gemini for one picture the way a person would: in a real browser, in a real
// signed-in session.
//
// This project used to call the Gemini Images API over HTTPS with a billed key. The
// pictures it returned were the weakest thing in the book — inconsistent between
// renders, stylistically flat, and often enough actively worse than no picture at
// all — while the *same model*, asked the same thing through gemini.google.com,
// produces art worth printing. The difference is not the prompt and is not the seat;
// it is the whole product around the model, which the API endpoint is not. So this
// fleet stopped paying for the bad one and drives the good one instead.
//
// There is no API key anywhere in this repository. What there is instead is a Chrome
// profile at GEMINI_PROFILE_DIR that a human signs in to exactly once
// (`scripts/gemini-login.sh`), after which this script reuses that profile headlessly
// for every render, forever. The credential is a cookie jar in a directory, owned by
// the person whose account it is.
//
// Driven over the Chrome DevTools Protocol with Node's built-in WebSocket, exactly
// like Title-Scout/annas.js next door: no npm dependencies, no puppeteer, nothing to
// install on the mini. One render per process — a fresh chat every time, so no
// previous picture is in context to be averaged into this one.
//
//   node tools/gemini_art.js --out FILE --prompt-file FILE [--ref FILE]... \
//                            [--aspect 2:3] [--timeout 300]
//
// Writes the PNG/JPEG to --out and prints ONE line of JSON on stdout:
//
//   {"ok":true,  "bytes":N, "width":W, "height":H, "mime":"image/png"}
//   {"ok":false, "kind":"not_signed_in|quota|refused|bad_reference|no_image|transient|setup",
//    "reason":"..."}
//
// `kind` is the contract that matters, because the three of them mean three
// different things to a book: `quota` is deferred and retried later, `refused` and
// `no_image` skip one slot down the retry ladder, and `not_signed_in` is a human
// errand that no amount of retrying fixes.
//
// Environment:
//   GEMINI_PROFILE_DIR  Chrome user-data-dir holding the signed-in session.
//   GEMINI_ART_HEADFUL  1 to watch it work (and to sign in). Default headless.
//   CHROME_BIN          path to Chrome. Default: the standard macOS install.
//   GEMINI_ART_DIAG_DIR if set, a failing render dumps a screenshot and the page
//                       text here, because "no image appeared" is unfixable without
//                       seeing what did.
//   GEMINI_ART_URL      test-only: point the driver at a local fixture page. Never set
//                       in production.

import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";

const CHROME = process.env.CHROME_BIN ||
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PROFILE = process.env.GEMINI_PROFILE_DIR ||
  join(homedir(), ".config", "fanfic", "chrome-gemini");
const HEADFUL = /^(1|true|yes|on)$/i.test(process.env.GEMINI_ART_HEADFUL || "");
const DIAG_DIR = process.env.GEMINI_ART_DIAG_DIR || "";
// The app, overridable ONLY so the test rig can point this at a local fixture that
// mimics the page's shape. Nothing in production sets it; `tests/fixtures/gemini_page.py`
// is the reason it exists. Being able to exercise Chrome launch, the CDP plumbing, the
// state machine, the upload, the three download fallbacks and the JSON contract without
// a Google account is worth one environment variable.
const APP_URL = process.env.GEMINI_ART_URL || "https://gemini.google.com/app";

// --- Arguments ---------------------------------------------------------------

function parseArgs(argv) {
  const out = { refs: [], timeout: 300 };
  for (let i = 0; i < argv.length; i++) {
    const flag = argv[i];
    const value = argv[i + 1];
    if (flag === "--out") { out.out = value; i++; }
    else if (flag === "--prompt-file") { out.promptFile = value; i++; }
    else if (flag === "--prompt") { out.prompt = value; i++; }
    else if (flag === "--ref") { out.refs.push(resolve(value)); i++; }
    else if (flag === "--aspect") { out.aspect = value; i++; }
    else if (flag === "--timeout") { out.timeout = Number(value) || 300; i++; }
  }
  return out;
}

// --- Chrome, over the DevTools protocol --------------------------------------

async function getJson(url) {
  const r = await fetch(url);
  return r.json();
}

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
      const msg = JSON.parse(ev.data);
      if (msg.id && c.pending.has(msg.id)) {
        const { resolve: ok, reject: no } = c.pending.get(msg.id);
        c.pending.delete(msg.id);
        msg.error ? no(new Error(JSON.stringify(msg.error))) : ok(msg.result);
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

  // Evaluate an expression and get its value back. `awaitPromise` so an async
  // expression (every fetch below) resolves before we read it.
  async eval(expression, { byValue = true } = {}) {
    const r = await this.send("Runtime.evaluate", {
      expression, returnByValue: byValue, awaitPromise: true,
    });
    if (r.exceptionDetails) {
      throw new Error(r.exceptionDetails.exception?.description ||
                      r.exceptionDetails.text || "evaluate failed");
    }
    return byValue ? r.result?.value : r.result;
  }

  async key(type, key, code, vk) {
    await this.send("Input.dispatchKeyEvent", {
      type, key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk,
    });
  }
}

// --- The page, read as a state machine ---------------------------------------
//
// Every selector below is a guess about somebody else's markup, and Google reships
// this app constantly. So nothing here depends on ONE selector: each probe tries a
// list and reports which arm matched, and the failure path dumps the page so the next
// person can see what it looks like now rather than guessing again from scratch.

// Where are we? Signed in at the composer, bounced to a login wall, or elsewhere.
//
// The naive version of this checked only for a composer, and a composer is NOT proof
// of a session: gemini.google.com serves a working chat to signed-out visitors, on a
// cut-down model, that answers text and politely declines every picture. A render
// against that comes back as "I can try to find an image like that for you, but can't
// create it right now" — a refusal, indistinguishable from a content refusal, which
// the ladder above would then burn every one of its rungs on before parking the slot.
// The whole book would quietly go text-only and nothing would say why.
//
// So the probe looks for the ACCOUNT, and treats a visible "Sign in" call to action as
// the negative. Both signals are checked because either alone is fragile: an account
// chip is markup Google reshuffles, and "Sign in" as a string could appear anywhere.
const PROBE_STATE = `(() => {
  const url = location.href;
  if (/accounts\.google\.com|ServiceLogin|signin/i.test(url)) return "signin";

  const signedIn = !!document.querySelector(
    'a[aria-label*="Google Account" i], a[href*="myaccount.google.com"], ' +
    '[data-test-id="account-menu"], img[alt*="Account" i]');
  const signInCta = [...document.querySelectorAll('a, button')].some(
    (el) => /^\s*sign in\s*$/i.test(el.textContent || ''));

  const editor = document.querySelector(
    'rich-textarea div[contenteditable="true"], div.ql-editor[contenteditable="true"], ' +
    'div[contenteditable="true"][role="textbox"], textarea[aria-label]');

  if (signInCta && !signedIn) return "signin";
  if (editor) return "composer";
  return "loading";
})()`;

// A second opinion, asked only when a render did not produce a picture. A guest
// session's refusal reads exactly like a policy refusal, and telling somebody to
// rephrase their prompt when the real answer is "sign in" wastes their afternoon.
const PROBE_SIGNED_OUT = `(() => {
  const signedIn = !!document.querySelector(
    'a[aria-label*="Google Account" i], a[href*="myaccount.google.com"], ' +
    '[data-test-id="account-menu"], img[alt*="Account" i]');
  const signInCta = [...document.querySelectorAll('a, button')].some(
    (el) => /^\s*sign in\s*$/i.test(el.textContent || ''));
  return signInCta && !signedIn;
})()`;

// The generated picture in the newest model response — and, just as importantly, NOT
// the reference we uploaded a moment ago.
//
// THE TRAP, caught on the first live reference render and worth the detail: an
// uploaded reference sits in the page at full size, and Gemini tends to answer a
// portrait reference with a portrait render, so the two are frequently the SAME
// DIMENSIONS. A "biggest candidate wins" rule is then a coin flip between them.
// Losing that flip writes the reference back to disk as though it were the render —
// which means every scene in a book would silently be the character sheet again, and
// it would look exactly like a working pipeline. The `.md5` of two consecutive
// renders being equal was the only symptom.
//
// So this does not rely on size to tell them apart. Three independent discriminators,
// because any one of them is a class name Google can change:
//
//   * scope to the last `model-response` and nothing else. `message-content` was in
//     this list and is the wrapper around the WHOLE conversation, user query included,
//     which is what let the upload into the candidate set at all.
//   * reject anything inside a user-query or file-preview container.
//   * reject the upload by its alt text, and prefer the render by its own.
const PROBE_IMAGES = `(() => {
  const responses = document.querySelectorAll('model-response, [data-test-id="model-response"]');
  const scope = responses.length ? responses[responses.length - 1] : null;
  if (!scope) return JSON.stringify([]);

  const REJECT_ANCESTOR =
    'user-query, user-query-content, user-query-file-preview, user-query-file-carousel, ' +
    '.file-preview-container, [data-test-id="user-query"]';
  const PREFER =
    'single-image img, generated-image img, .generated-image img, img[alt*="AI generated" i]';

  const out = [];
  for (const img of scope.querySelectorAll('img')) {
    const src = img.currentSrc || img.src || '';
    if (!src || src.startsWith('data:image/gif')) continue;
    if (!img.complete) continue;
    const w = img.naturalWidth, h = img.naturalHeight;
    if (w < 256 || h < 256) continue;                    // avatars, icons, spinners
    if (img.closest(REJECT_ANCESTOR)) continue;          // an attachment, not a render
    const alt = img.getAttribute('alt') || '';
    if (/upload/i.test(alt)) continue;                   // "Uploaded image preview"
    out.push({ src, width: w, height: h, generated: img.matches(PREFER) });
  }
  return JSON.stringify(out);
})()`;

// Whether the model is still working. Gemini keeps a stop-generating control up for
// exactly as long as it is producing, which is a far better readiness signal than any
// timer: a picture takes anywhere from eight seconds to two minutes.
const PROBE_BUSY = `(() => {
  const stop = document.querySelector(
    'button[aria-label*="Stop" i], button[aria-label*="stop response" i], ' +
    '.stop-icon, [data-test-id="stop-button"]');
  return !!stop;
})()`;

// Whether the model has begun answering at all. Needed to tell "has not started yet"
// from "finished and produced nothing", which look identical from the text alone and
// which want opposite responses — keep waiting, versus stop immediately.
const PROBE_HAS_RESPONSE = `(() => document.querySelectorAll(
  'model-response, [data-test-id="model-response"]').length > 0)()`;

// The newest response as text, for the two outcomes that are not a picture: a refusal
// and a usage ceiling.
//
// Scoped to `model-response` and NOT `message-content`, for the same reason the image
// probe is: `message-content` wraps the whole conversation including the prompt we
// just sent. A scene description mentioning what a character "can't create" would
// then read back as the model refusing, and the slot would drop a rung down the
// ladder for a sentence we wrote ourselves.
const PROBE_TEXT = `(() => {
  const scopes = document.querySelectorAll('model-response, [data-test-id="model-response"]');
  if (!scopes.length) return '';
  return (scopes[scopes.length - 1].innerText || '').slice(0, 1200);
})()`;

const LIMIT_PATTERNS = [
  /you'?ve reached your limit/i,
  /limit for .{0,40}image/i,
  /try again (later|tomorrow)/i,
  /you'?ve reached your (daily |)limit/i,
  /rate limit/i,
  /too many requests/i,
  /upgrade to (continue|keep)/i,
];

// The page says things mid-flight that read exactly like a verdict. "Creating your
// image" is the obvious one; the refusal text below can also appear transiently BEFORE
// the image starts, which is not a refusal, it is the app changing its mind out loud.
const WORKING_PATTERNS = [
  /creating your image/i,
  /generating/i,
  /working on it/i,
];

// A refusal about the UPLOAD rather than the request. Distinct because the remedy is
// completely different: the prompt is fine and does not want simplifying — one of the
// attached pictures is unacceptable to Gemini, and the render should be retried
// without it.
//
// Seen live on Satele Shan, whose wiki art is a photoreal 3D promotional render; the
// classifier appears to read that as a photograph of a real person. A rejected upload
// also never produces an attachment chip, so this is the same failure that shows up
// earlier as "files were set but no attachment preview appeared".
const BAD_REFERENCE_PATTERNS = [
  /can'?t help with that image/i,
  /try uploading another image/i,
  /unable to process the (uploaded |)image/i,
  /can'?t (analyze|analyse|identify) (the |)(people|person|faces?) in/i,
];

const REFUSAL_PATTERNS = [
  // "There are a lot of people I can help with, but I can't depict some public
  // figures." Gemini reads this project's reference art — photoreal 3D promotional
  // renders — as photographs of real humans, and then declines to draw the person.
  // Worth its own pattern rather than leaving it to the timeout: unmatched, this cost
  // a full 600-second wait before the slot could even move to its next rung.
  /can'?t depict some public figures/i,
  /can'?t (depict|generate images of) (real |)(people|persons|individuals)/i,
  /do you have anyone else in mind/i,
  /can'?t (help with|create|generate|make)/i,
  /unable to (create|generate)/i,
  /i'?m not able to (create|generate)/i,
  /violates? .{0,30}polic/i,
  /against my guidelines/i,
];

function classifyText(text) {
  for (const re of LIMIT_PATTERNS) if (re.test(text)) return "quota";
  // Checked before the general refusal list, whose wording it would otherwise match.
  for (const re of BAD_REFERENCE_PATTERNS) if (re.test(text)) return "bad_reference";
  for (const re of REFUSAL_PATTERNS) if (re.test(text)) return "refused";
  return null;
}

// --- Getting the actual bytes ------------------------------------------------
//
// Three ways, tried in order, because each one fails on a different kind of URL and
// between them they cover every shape Gemini has served. A picture visible on screen
// that we could not save is the most annoying possible failure, so this tries hard.

async function imageBytes(cdp, src, frameId) {
  // 1. Chrome's own copy of the resource. Best arm by a distance: it is the ORIGINAL
  //    bytes, at the original compression, with no re-encode — and it works on a
  //    revoked blob, which is the normal case here.
  //
  //    This arm silently did nothing for a while. `Page.getFrameTree` returns a Frame
  //    whose property is `id`; the code destructured `{ frameId }` off it, passed
  //    undefined, and fell through to arms that cannot serve a blob. The symptom was
  //    "found a 572x1024 image but could not download it (no bytes)" — a picture
  //    visibly on screen that we could not save, which is the most annoying failure
  //    this driver has. Every fallback below it was working as designed; the bug was
  //    that the good arm never ran.
  try {
    const r = await cdp.send("Page.getResourceContent", { frameId, url: src });
    if (r?.content) {
      return Buffer.from(r.content, r.base64Encoded ? "base64" : "utf-8");
    }
  } catch { /* fall through */ }

  // 2. In-page fetch. Works for a blob that has not been revoked and for anything
  //    same-origin, and inherits the session's cookies for free.
  try {
    const b64 = await cdp.eval(`(async () => {
      try {
        const r = await fetch(${JSON.stringify(src)});
        if (!r.ok) return "";
        const buf = new Uint8Array(await r.arrayBuffer());
        let s = "";
        for (let i = 0; i < buf.length; i += 0x8000) {
          s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
        }
        return btoa(s);
      } catch (e) { return ""; }
    })()`);
    if (b64) return Buffer.from(b64, "base64");
  } catch { /* fall through */ }

  // 3. Re-encode what the renderer already decoded. The picture is on screen, so the
  //    bitmap exists whatever happened to the URL that delivered it — this arm works
  //    on a revoked blob and needs no network at all. It is third rather than first
  //    because it is a re-encode: a lossless PNG of the decoded image, which is
  //    correct but several times the size of the JPEG it came from.
  //
  //    Only possible because the blob is same-origin, so the canvas is not tainted.
  //    A cross-origin CDN image without CORS headers would throw here, which is
  //    exactly why this is not the only fallback.
  try {
    const dataUrl = await cdp.eval(`(() => {
      try {
        const imgs = [...document.querySelectorAll('img')];
        const img = imgs.find((i) => (i.currentSrc || i.src) === ${JSON.stringify(src)});
        if (!img || !img.naturalWidth) return "";
        const c = document.createElement('canvas');
        c.width = img.naturalWidth;
        c.height = img.naturalHeight;
        c.getContext('2d').drawImage(img, 0, 0);
        return c.toDataURL('image/png');
      } catch (e) { return ""; }
    })()`);
    const comma = (dataUrl || "").indexOf(",");
    if (comma > 0) return Buffer.from(dataUrl.slice(comma + 1), "base64");
  } catch { /* fall through */ }

  // 4. Plain fetch from Node with the session's cookies attached. Cannot serve a
  //    blob: URL at all, and exists for the day Gemini goes back to serving plain
  //    https image URLs off a CDN.
  try {
    if (/^https?:/.test(src)) {
      const { cookies } = await cdp.send("Network.getAllCookies");
      const jar = cookies
        .filter((c) => /google|gstatic|googleusercontent/.test(c.domain))
        .map((c) => `${c.name}=${c.value}`).join("; ");
      const r = await fetch(src, { headers: { cookie: jar } });
      if (r.ok) return Buffer.from(await r.arrayBuffer());
    }
  } catch { /* fall through */ }

  return null;
}


function sniff(buf) {
  if (!buf || buf.length < 12) return null;
  if (buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])))
    return "image/png";
  if (buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return "image/jpeg";
  if (buf.subarray(0, 4).toString() === "RIFF" && buf.subarray(8, 12).toString() === "WEBP")
    return "image/webp";
  return null;
}

// --- Diagnostics -------------------------------------------------------------

async function dump(cdp, tag) {
  if (!DIAG_DIR) return;
  try {
    mkdirSync(DIAG_DIR, { recursive: true });
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const shot = await cdp.send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(DIAG_DIR, `${stamp}-${tag}.png`),
                  Buffer.from(shot.data, "base64"));
    const text = await cdp.eval(
      `(document.body ? document.body.innerText : "").slice(0, 20000)`);
    writeFileSync(join(DIAG_DIR, `${stamp}-${tag}.txt`), String(text || ""));
  } catch { /* diagnostics never fail a render */ }
}

function notSignedInMessage(detail) {
  return `the Chrome profile at ${PROFILE} is not signed in to Gemini (${detail}). ` +
         `Run scripts/gemini-login.sh once, sign in, close the window, and renders ` +
         `resume by themselves.`;
}

// --- The render --------------------------------------------------------------

async function render(cdp, args, prompt) {
  const deadline = Date.now() + args.timeout * 1000;
  const left = () => Math.max(1000, deadline - Date.now());

  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("DOM.enable");
  await cdp.send("Network.enable");

  // A FRESH CHAT for every picture. Gemini carries a conversation, and a second
  // render in the same thread is drawn "like the last one" — which is precisely the
  // sameness that made the API's output unusable, reintroduced from the other side.
  await cdp.send("Page.navigate", { url: APP_URL });

  const state = await waitFor(async () => {
    const s = await cdp.eval(PROBE_STATE);
    return s === "loading" ? null : s;
  }, Math.min(60000, left()), 700);

  if (state !== "composer") {
    await dump(cdp, "signin");
    return { ok: false, kind: "not_signed_in",
             reason: notSignedInMessage(`page state: ${state || "never loaded"}`) };
  }

  // `.id`, NOT `.frameId` — a Frame's identifier is `id`, and getting this wrong
  // disables the best download arm without raising anything. See `imageBytes`.
  const frameId = (await cdp.send("Page.getFrameTree")).frameTree.frame.id;

  // The composer existing is not the same as the toolbar being wired up. A short
  // settle costs a second and removes a whole class of "the button did nothing".
  await sleep(1200);

  // Attach the reference pictures. These are the locked character sheets and the
  // source art off each character's own wiki, and they are the entire answer to
  // visual drift across a series: the words cannot carry a face, so the faces are
  // attached. A render that silently lost them would look fine and be wrong, so a
  // failed attach is a hard error rather than a degraded render.
  if (args.refs.length) {
    const attached = await attachRefs(cdp, args.refs, left());
    if (attached !== true) {
      await dump(cdp, "upload");
      // A rejected upload never produces a preview chip, so "no preview appeared" and
      // an explicit "can't help with that image" are one failure wearing two faces.
      // Both want the same remedy: drop the reference, keep the prompt.
      const kind = /no attachment preview/.test(String(attached))
        ? "bad_reference" : "transient";
      return { ok: false, kind,
               reason: `could not attach ${args.refs.length} reference picture(s): ${attached}` };
    }
  }

  // Type the prompt. `Input.insertText` rather than setting `innerText`, because the
  // composer is a rich-text component that tracks its own model and ignores a DOM
  // write — the send button stays disabled and nothing is ever sent.
  await cdp.eval(`(() => {
    const el = document.querySelector(
      'rich-textarea div[contenteditable="true"], div.ql-editor[contenteditable="true"], ' +
      'div[contenteditable="true"][role="textbox"], textarea[aria-label]');
    if (el) { el.focus(); el.click(); }
    return !!el;
  })()`);
  await cdp.send("Input.insertText", { text: prompt });
  await sleep(400);

  const sent = await cdp.eval(`(() => {
    const b = document.querySelector(
      'button[aria-label*="Send" i]:not([disabled]), button.send-button:not([disabled]), ' +
      '[data-test-id="send-button"]:not([disabled])');
    if (b) { b.click(); return true; }
    return false;
  })()`);
  if (!sent) {
    // No send button we recognise: press Enter, which the composer also honours.
    await cdp.key("keyDown", "Enter", "Enter", 13);
    await cdp.key("keyUp", "Enter", "Enter", 13);
  }

  // WHY THE PROMPT SOMETIMES NEVER LEAVES THE COMPOSER — diagnosed, not fixed.
  //
  // When a reference upload fails, Gemini marks the attachment chip with an error and
  // keeps the send control DISABLED. The prompt then sits here and can never go: no
  // amount of clicking or pressing Enter helps, because there is nothing enabled to
  // click. The driver waits out the entire deadline and reports
  // `no image after Ns; last response text: ""`, which reads as "Gemini said nothing"
  // and actually means "we were never able to ask".
  //
  // Evidence, on 2026-08-31: `state/image-diagnostics/2026-08-31T22-05-18Z-timeout.png`
  // shows five reference chips (valis, t7-o1, lord-scourge, ref1, ref2) each carrying an
  // error icon, the prompt below them, and the send arrow greyed out. Across that
  // evening, renders conditioned on references fell 12/hr -> 0/hr while reference-FREE
  // renders kept working at ~3/hr. Two earlier send-retry schemes were tried and
  // reverted; both were retrying a click against a control that was disabled.
  //
  // THE FIX IS OBVIOUS AND UNTESTABLE HERE: treat "attachments present and send still
  // disabled" as `bad_reference`, which sheds the references and re-asks with the
  // prose-anchored prompt — the path already built for exactly this. I wrote it and
  // backed it out, because `tests/fixtures/gemini_page.py` does not model a failed
  // upload: the fixture composer keeps its text after a successful send, so the check
  // fired on every render carrying references and broke 13 of the 21 browser tests.
  //
  // To do it properly: first teach the fixture to serve a failed-upload state (errored
  // chip + disabled send), then write the check against it. Do not ship this without
  // that fixture — the failure mode is "every reference is silently discarded", which
  // looks like working software and quietly destroys visual consistency.

  // Wait for a picture. Two conditions, and both are needed: an image large enough to
  // be a render, AND the generation actually finished. Grabbing the first arm alone
  // caught progressive placeholders and saved a blurred half-image.
  let lastText = "";
  // Consecutive polls where the model has answered, is not working, and has produced
  // neither a picture nor any words. Twice tonight the page settled into exactly that
  // and the driver waited out the full ten-minute timeout for something that was never
  // coming. A handful of quiet polls is enough to call it.
  let settledEmpty = 0;
  // When the page FIRST claimed to be working, so an endless "Creating your image"
  // can be told from a slow one. Observed renders finish in 20-40s; twice now the
  // page has sat in that state for the entire ten-minute budget and produced nothing.
  // Four minutes is generous headroom over anything real and saves six of those ten.
  let workingSince = 0;
  const WORKING_MAX_MS = Number(process.env.GEMINI_ART_WORKING_MAX_MS) || 240000;
  const found = await waitFor(async () => {
    const text = String(await cdp.eval(PROBE_TEXT) || "");
    if (text) lastText = text;

    // ORDER MATTERS HERE, and getting it wrong cost a render that was already on its
    // way. Gemini emitted "I'm just a language model and can't help with that" and
    // then began generating anyway — so a text verdict read before the page has
    // settled is not a verdict, it is a snapshot of the app mid-decision. Judge the
    // words only once nothing is still moving.
    const busy = await cdp.eval(PROBE_BUSY);
    const working = WORKING_PATTERNS.some((re) => re.test(text));

    const images = JSON.parse(await cdp.eval(PROBE_IMAGES) || "[]");
    if (images.length && !busy && !working) return { images };

    if (busy || working) {
      settledEmpty = 0;
      if (!workingSince) workingSince = Date.now();
      if (Date.now() - workingSince > WORKING_MAX_MS) {
        return { verdict: "no_image",
                 text: `the page stayed in a working state for ` +
                       `${Math.round(WORKING_MAX_MS / 1000)}s without producing an ` +
                       `image (last said: ${JSON.stringify(text.slice(0, 80))})` };
      }
      return null;                                             // still going
    }
    workingSince = 0;                                          // it stopped working
    if (images.length) { settledEmpty = 0; return null; }      // settling on a picture

    const verdict = classifyText(text);
    if (verdict) return { verdict, text };

    // Answered, stopped, and said nothing. Give it a few polls in case the DOM is
    // mid-swap, then stop rather than burning the whole budget on silence.
    const answered = await cdp.eval(PROBE_HAS_RESPONSE);
    settledEmpty = (answered && text.trim().length < 3) ? settledEmpty + 1 : 0;
    if (settledEmpty >= 6) {
      return { verdict: "no_image",
               text: "the reply finished with neither a picture nor any text" };
    }
    return null;
  }, left(), 1500);

  if (!found) {
    await dump(cdp, "timeout");
    return { ok: false, kind: "transient",
             reason: `no image after ${args.timeout}s; last response text: ` +
                     `${JSON.stringify(lastText.slice(0, 200))}` };
  }
  if (found.verdict) {
    // A guest session declines every picture in the language of a policy refusal. Ask
    // the page who it thinks we are before blaming the prompt.
    if ((found.verdict === "refused" || found.verdict === "bad_reference")
        && await cdp.eval(PROBE_SIGNED_OUT)) {
      await dump(cdp, "signin");
      return { ok: false, kind: "not_signed_in", reason: notSignedInMessage(
        "the session went to a signed-out guest chat, which answers text and declines " +
        "every picture") };
    }
    await dump(cdp, found.verdict);
    return { ok: false, kind: found.verdict,
             reason: found.text.replace(/\s+/g, " ").slice(0, 300) };
  }

  // An image the page positively identifies as generated always beats one that is
  // merely large; size only breaks ties within a class. Size alone was what let an
  // uploaded reference win.
  const best = found.images.sort((a, b) =>
    (b.generated ? 1 : 0) - (a.generated ? 1 : 0) ||
    b.width * b.height - a.width * a.height)[0];
  const buf = await imageBytes(cdp, best.src, frameId);
  const mime = sniff(buf);
  if (!buf || !mime) {
    await dump(cdp, "download");
    return { ok: false, kind: "transient",
             reason: `found a ${best.width}x${best.height} image but could not ` +
                     `download it (${buf ? buf.length + " bytes, unrecognised format"
                                         : "no bytes"})` };
  }

  mkdirSync(dirname(resolve(args.out)), { recursive: true });
  writeFileSync(resolve(args.out), buf);
  return { ok: true, bytes: buf.length, width: best.width, height: best.height, mime };
}

// Attach reference images to the composer. Returns true, or a string saying why not.
//
// This is the load-bearing half of visual consistency — the locked character sheets
// are how a face survives forty-six chapters — so it is deliberately patient and
// deliberately picky, and it fails loudly rather than rendering without them.
//
// What the live page actually does, measured rather than assumed:
//
//   * there is NO file input until the "Upload & tools" menu is opened. The first
//     version checked once, clicked once, slept 600ms and gave up — which is how the
//     first real sheet with references failed with "no file input in the page".
//   * once opened, TWO inputs appear. One of them is Drive. `querySelector` takes
//     whichever comes first in the DOM, which is a coin flip on the one that matters.
async function attachRefs(cdp, refs, budgetMs) {
  const deadline = Date.now() + Math.min(90000, budgetMs);

  // Open the menu if the input is not already there, and keep trying while there is
  // budget: a freshly navigated page may not have wired the button up yet.
  let handles = await fileInputs(cdp);
  for (let attempt = 0; !handles.length && Date.now() < deadline && attempt < 4;
       attempt++) {
    await cdp.eval(`(() => {
      const b = document.querySelector(
        'button[aria-label*="upload" i], button[aria-label*="add file" i], ' +
        'button[aria-label*="attach" i], uploader button, button.upload-card-button');
      if (b) b.click();
      return !!b;
    })()`);
    // Poll rather than sleep a fixed amount — it lands in ~300ms on a warm page and
    // takes noticeably longer on a cold one.
    handles = await waitFor(async () => {
      const found = await fileInputs(cdp);
      return found.length ? found : null;
    }, 4000, 250) || [];
  }
  if (!handles.length) return "no file input in the page";

  // Try each input until one takes the files. The Drive picker is also an
  // `input[type=file]` and silently accepts nothing useful, so "the first one" is not
  // good enough — the test is whether a preview chip appears afterwards.
  let lastError = "";
  for (const objectId of handles) {
    try {
      await cdp.send("DOM.setFileInputFiles", { files: refs, objectId });
    } catch (e) {
      lastError = e.message;
      continue;
    }
    const ready = await waitFor(async () => {
      const n = await cdp.eval(`(() => document.querySelectorAll(
        'user-query-file-preview, .file-preview, .attachment-container img, ' +
        '[data-test-id="file-chip"], uploader-file-preview, .uploaded-file-chip'
        ).length)()`);
      return Number(n) >= refs.length ? true : null;
    }, Math.max(4000, Math.min(60000, deadline - Date.now())), 500);
    // KNOWN GAP: a chip that APPEARED is not a chip that UPLOADED.
    //
    // This counts previews and returns success at `>= refs.length`. When Gemini fails
    // an upload it still renders a chip — with an error icon on it — so the count is
    // satisfied, this returns true, and the caller proceeds. Gemini then keeps the send
    // control DISABLED while any attachment is errored, so the prompt can never leave
    // the composer and the render times out reporting
    // `no image after Ns; last response text: ""`.
    //
    // Seen 2026-08-31: `state/image-diagnostics/2026-08-31T22-05-18Z-timeout.png` shows
    // five chips each carrying an error icon, the prompt below, and the send arrow
    // greyed out. Reference-carrying renders went 12/hr -> 0/hr while reference-free
    // ones kept working. Two send-retry schemes were written and reverted before the
    // cause was found; both were retrying a click against a disabled control.
    //
    // THE FIX, and it is small: after the chips appear, check whether any is in an
    // error state, and if so return a message matching /no attachment preview/ so the
    // caller maps it to `bad_reference` — which already sheds the references and
    // re-asks with the prose-anchored prompt. All of that machinery exists and is
    // tested; only the detection is missing.
    //
    // NOT DONE because it cannot be tested yet: `tests/fixtures/gemini_page.py` has no
    // failed-upload state, so any check written against a guessed error selector fires
    // on healthy chips too. An earlier attempt did exactly that and broke 13 of the 21
    // browser tests. **Teach the fixture to serve an errored chip with a disabled send
    // first.** The failure mode of getting this wrong is "every reference silently
    // discarded", which looks like working software.
    if (ready) return true;
    lastError = "files were set but no attachment preview appeared";
  }
  return lastError || "no file input accepted the references";
}


// Every file input on the page, as CDP object ids. Plural because the upload menu
// exposes more than one and only some of them take a local file.
async function fileInputs(cdp) {
  const count = await cdp.eval(
    `document.querySelectorAll('input[type="file"]').length`);
  const out = [];
  for (let i = 0; i < Number(count || 0); i++) {
    const r = await cdp.eval(
      `document.querySelectorAll('input[type="file"]')[${i}]`, { byValue: false });
    if (r?.objectId) out.push(r.objectId);
  }
  return out;
}

// --- Entry point -------------------------------------------------------------

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.out) return { ok: false, kind: "setup", reason: "--out is required" };

  let prompt = args.prompt || "";
  if (args.promptFile) {
    try { prompt = readFileSync(args.promptFile, "utf-8"); }
    catch (e) { return { ok: false, kind: "setup", reason: `--prompt-file: ${e.message}` }; }
  }
  prompt = prompt.trim();
  if (!prompt) return { ok: false, kind: "setup", reason: "empty prompt" };
  // Newlines send the message, so the prompt travels as one line. The structure the
  // prompt builder puts in is carried by its own wording, not by its line breaks.
  prompt = prompt.replace(/\s*\n\s*/g, "  ");

  mkdirSync(PROFILE, { recursive: true });
  const port = 9500 + Math.floor(Math.random() * 400);
  const flags = [
    "--no-first-run", "--no-default-browser-check", "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=Translate,MediaRouter",
    "--window-size=1400,1100",
    `--user-data-dir=${PROFILE}`,
    `--remote-debugging-port=${port}`,
    APP_URL,
  ];
  // `--headless=new` runs the same renderer as the visible browser, which matters:
  // old headless was detectable and served a degraded app. Set GEMINI_ART_HEADFUL=1
  // to watch a render, which is the only way to debug a selector that moved.
  if (!HEADFUL) flags.unshift("--headless=new");

  const chrome = spawn(CHROME, flags, { stdio: "ignore" });
  try {
    const version = await waitFor(async () => {
      try { return await getJson(`http://127.0.0.1:${port}/json/version`); }
      catch { return null; }
    }, 25000);
    if (!version) {
      return { ok: false, kind: "setup",
               reason: `Chrome devtools never came up on port ${port}. Is another ` +
                       `Chrome already using the profile at ${PROFILE}? Close it — ` +
                       `a profile can only be open once.` };
    }

    const targets = await getJson(`http://127.0.0.1:${port}/json/list`);
    const page = targets.find((t) => t.type === "page");
    if (!page) return { ok: false, kind: "transient", reason: "no page target" };

    const cdp = await CDP.connect(page.webSocketDebuggerUrl);
    try {
      return await render(cdp, args, prompt);
    } finally {
      try { cdp.ws.close(); } catch { /* closing is best-effort */ }
    }
  } finally {
    chrome.kill("SIGKILL");
  }
}

main()
  .then((result) => {
    console.log(JSON.stringify(result));
    process.exit(result.ok ? 0 : 1);
  })
  .catch((e) => {
    console.log(JSON.stringify({ ok: false, kind: "transient", reason: e.message }));
    process.exit(1);
  });
