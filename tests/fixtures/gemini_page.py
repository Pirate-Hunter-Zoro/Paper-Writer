"""A fake Gemini, served locally, so the browser driver can be tested without Google.

## Why this exists

`tools/gemini_art.js` is the least testable thing in the project by construction: it
drives a real browser against somebody else's web app, over a session only a human can
create. The temptation is to declare it untestable and ship it on one manual look.

That would leave the *entire* mechanism unverified — Chrome launch, the CDP plumbing,
the signed-in/signed-out state machine, prompt insertion into a rich-text composer,
reference upload through a hidden file input, the three download fallbacks, the
`kind` contract the Python side dispatches on, and the sanity floor. None of that is
Google-specific. Only the **selectors** are.

So this serves a page with the same *shape* as Gemini's — the same element roles,
the same account chip, the same `model-response` container, the same hidden file
input, the same asynchronous "thinking then an image appears" behaviour — and the
driver is pointed at it with `GEMINI_ART_URL`. Everything except "does this selector
match Google's current markup" is then a normal, repeatable test.

**What this cannot prove, stated plainly so nobody mistakes a green run for a working
renderer:** that the real app's composer, send button, file input, response container
or image element still match the selector lists in the driver. That question has
exactly one answer, and it is a live render against a signed-in account.

## Scenarios

Query string picks the behaviour, so one fixture covers the whole contract:

    ?scenario=ok            a real render appears after a short think
    ?scenario=slow          appears only after the "stop generating" control clears
    ?scenario=two           a thumbnail and a full render; the big one must win
    ?scenario=decoy         an uploaded reference of the SAME size as the render, in
                            the real app's containers. The render must still win.
    ?scenario=blob          the image is a blob: URL (the in-page fetch path)
    ?scenario=tiny          a 64x64 image, which the sanity floor must reject
    ?scenario=refused       a policy refusal
    ?scenario=quota         a usage ceiling
    ?scenario=signedout     the guest chat: a composer, no account, declines pictures
    ?scenario=silent        never produces anything, to exercise the timeout
    ?scenario=empty         answers with a completely empty response bubble — the
                            live hang that burned two ten-minute timeouts
    ?scenario=uploadfail    the upload ERRORS: chips appear (so "a chip appeared" is
                            satisfied) carrying the real app's error markup, and the
                            send button does nothing. This is the live failure of
                            2026-09-01 — the markup below is copied from the page.
    ?scenario=stuck         claims to be working forever and never produces anything —
                            the other live hang, "Creating your image" for ten minutes

    python3 tests/fixtures/gemini_page.py [port]
"""

import struct
import sys
import threading
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer


def png(width, height, seed=7):
    """A real, valid PNG. Valid rather than a stub header, because the driver reads
    `naturalWidth` off a decoded image — a fake header renders as a broken image and is
    never picked up.

    **Noisy rather than a flat colour, and that detail is load-bearing.** The first
    version filled a flat blue, and a flat 1024x1536 PNG compresses to under 8 KB —
    which is smaller than any real illustration and would have made the sanity-floor
    test pass against a file nothing like what Gemini returns. A fixture that is easier
    than reality tests the wrong thing."""
    rand = _lcg(seed)
    raw = b"".join(
        b"\x00" + bytes(next(rand) for _ in range(width * 3)) for _ in range(height))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def _lcg(seed):
    """A tiny deterministic PRNG. `random` would do, but seeding it here would perturb
    the global stream for anything else in the process, and a fixture should not have
    side effects on its caller."""
    state = seed or 1
    while True:
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        yield (state >> 16) & 0xFF


# The page. Deliberately mirrors the element roles the driver probes for:
#   - an account chip           -> `a[aria-label*="Google Account"]`
#   - a rich-text composer      -> `rich-textarea div[contenteditable="true"]`
#   - a send button             -> `button[aria-label*="Send"]`
#   - a hidden file input       -> `input[type="file"]`
#   - a response container      -> `model-response`
#   - a stop-generating control -> `button[aria-label*="Stop"]`
PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Gemini (fixture)</title></head>
<body>
<header>
  __ACCOUNT__
</header>

<main>
  <div id="conversation"></div>

  <rich-textarea>
    <div class="ql-editor" contenteditable="true" role="textbox"
         aria-label="Enter a prompt here"></div>
  </rich-textarea>

  <!-- Hidden behind the "+" menu in the real app, and present in the DOM either way,
       which is exactly why the driver looks for it before clicking anything. -->
  <input type="file" multiple style="display:none" id="upload">
  <button aria-label="Open upload menu" id="uploadmenu">+</button>
  <div id="chips"></div>

  <button aria-label="Send message" id="send">Send</button>
  <div id="stopwrap"></div>
</main>

<script>
const SCENARIO = new URLSearchParams(location.search).get("scenario") || "ok";
const chips = document.getElementById("chips");

// Mirror the real app's upload feedback: a chip per attached file, which is what the
// driver waits for before it will send.
document.getElementById("upload").addEventListener("change", (ev) => {
  for (const f of ev.target.files) {
    const d = document.createElement("div");
    d.className = "file-preview";
    if (SCENARIO === "uploadfail") {
      // Verbatim shape from the live app on 2026-09-01: the chip is PRESENT, so a
      // check that counts previews is satisfied, and the failure is carried by a
      // class and an icon name. Note there is no `disabled` anywhere -- the send
      // button stays clickable and simply ignores the click, which is why every
      // send-retry scheme written against "the button is disabled" was chasing a
      // thing that was never in the DOM.
      // The real chip is OPTIMISTIC: it appears healthy, sits in a loading state,
      // and flips to an error only once the upload actually fails. A check made the
      // instant chips appear therefore sees nothing wrong — which is exactly how the
      // first version of this fix passed its test and changed nothing live.
      d.innerHTML = '<gem-attachment class="gem-attachment gem-attachment-loading">' +
                    '<span class="gem-attachment-title">' + f.name + '</span>' +
                    '</gem-attachment>';
      setTimeout(() => {
      d.innerHTML =
        '<gem-attachment class="gem-attachment gem-attachment-loading-error ' +
        'gem-attachment-tile" tabindex="0"><mat-basic-chip class="mat-mdc-chip">' +
        '<span class="gem-attachment-content">' +
        '<gem-icon fonticonname="error" class="gem-attachment-icon"></gem-icon>' +
        '<span class="gem-attachment-title">' + f.name + '</span>' +
        '</span></mat-basic-chip></gem-attachment>';
      }, 2500);
    } else {
      d.innerHTML = '<img alt="' + f.name + '" width="40" height="40">';
    }
    chips.appendChild(d);
  }
  window.__uploaded = ev.target.files.length;
  if (SCENARIO === "uploadfail") {
    // Doomed the moment the file is set, even though the chip does not say so for
    // another 2.5s. The send below must consult THIS, not the DOM: the driver sends
    // within a second or two of attaching, well before the error is visible, and the
    // real app drops that send anyway.
    window.__uploadDoomed = true;
    return;                                // nothing is attached to the conversation
  }

  // Reproduce the real app's attachment markup, because it is the source of the
  // nastiest bug this driver has had. gemini.google.com renders an uploaded
  // reference at FULL SIZE inside `user-query-file-preview`, and answers a portrait
  // reference with a portrait render -- so the attachment and the render are
  // routinely the same dimensions, and a "biggest wins" rule picks between them at
  // random. Losing that flip writes the reference back to disk as the render, which
  // in a book means every scene is silently the character sheet again.
  const uq = document.createElement("user-query");
  uq.innerHTML =
    '<user-query-file-carousel class="query-file-carousel">' +
    '<div class="file-preview-container">' +
    '<user-query-file-preview class="query-file-preview">' +
    '<button class="preview-image-button">' +
    '<img class="preview-image" alt="Uploaded image preview" src="/img?w=1024&h=1536">' +
    '</button></user-query-file-preview></div></user-query-file-carousel>';
  document.getElementById("conversation").appendChild(uq);
});

function busy(on) {
  document.getElementById("stopwrap").innerHTML =
    on ? '<button aria-label="Stop response">stop</button>' : '';
}

function respond(html) {
  const el = document.createElement("model-response");
  el.innerHTML = html;
  document.getElementById("conversation").appendChild(el);
}

// The generated picture, in the containers the real app actually uses.
function generated(w, h) {
  return '<response-element><generated-image class="luminous-layout">' +
         '<single-image class="generated-image"><div class="image-container">' +
         '<button class="image-button">' +
         '<img class="image" alt=", AI generated" src="/img?seed=42&w=' + w + '&h=' + h + '">' +
         '</button></div></single-image></generated-image></response-element>';
}

// `message-content` wraps the WHOLE conversation, user query included. It was in the
// driver's scope list, which is how an attachment became a render candidate.
function wrapConversation() {
  const conv = document.getElementById("conversation");
  if (conv.closest("message-content")) return;
  const mc = document.createElement("message-content");
  conv.parentNode.insertBefore(mc, conv);
  mc.appendChild(conv);
}
wrapConversation();

async function blobUrl(src) {
  const r = await fetch(src);
  return URL.createObjectURL(await r.blob());
}

document.getElementById("send").addEventListener("click", async () => {
  // The live app does NOT disable this button when an attachment fails; it just
  // drops the click. Reproducing the real behaviour, not a plausible one.
  if (window.__uploadDoomed) return;
  const editor = document.querySelector('.ql-editor');
  const prompt = editor.innerText;
  window.__prompt = prompt;               // so the test can assert what was received
  respond('<div class="you">' + prompt + '</div>');
  busy(true);

  await new Promise((r) => setTimeout(r, 300));

  if (SCENARIO === "silent") { busy(false); return; }

  if (SCENARIO === "stuck") {
    // Never stops "working". The driver must not wait this out forever.
    respond("Creating your image");
    return;                                    // busy stays on, deliberately
  }

  if (SCENARIO === "empty") {
    // What the live page actually did: a response element containing nothing at all,
    // with generation finished. No image, no words, no refusal — a state the wait
    // loop had no exit condition for.
    busy(false);
    respond("");
    return;
  }

  if (SCENARIO === "refused" || SCENARIO === "signedout") {
    busy(false);
    respond("I can try to find an image like that for you, but can't create it right now.");
    return;
  }
  if (SCENARIO === "quota") {
    busy(false);
    respond("You've reached your limit for image generation. Try again later.");
    return;
  }
  if (SCENARIO === "tiny") {
    busy(false);
    respond('<img src="/img?w=64&h=64">');
    return;
  }
  if (SCENARIO === "decoy") {
    // Same dimensions as the attachment above, deliberately.
    busy(false);
    respond(generated(1024, 1536));
    return;
  }
  if (SCENARIO === "two") {
    busy(false);
    respond('<img src="/img?w=300&h=300"><img src="/img?w=1024&h=1536">');
    return;
  }
  if (SCENARIO === "blob") {
    const u = await blobUrl("/img?w=1024&h=1536");
    busy(false);
    respond('<img src="' + u + '">');
    return;
  }
  if (SCENARIO === "slow") {
    // The image is in the DOM while generation is still running. A driver that grabs
    // the first big image it sees would save this half-finished; it must wait for the
    // stop control to clear. The real app streams a progressive placeholder here.
    respond('<img src="/img?w=1024&h=1536">');
    await new Promise((r) => setTimeout(r, 2500));
    busy(false);
    return;
  }
  busy(false);
  respond(generated(1024, 1536));
});
</script>
</body></html>
"""

ACCOUNT_IN = ('<a aria-label="Google Account: Test User" '
              'href="https://myaccount.google.com/">account</a>')
# The guest header: no account chip, and a "Sign in" call to action. This is the case
# that cost real debugging time — a guest gets a working composer, so a driver checking
# for a composer concludes it is signed in and every render comes back as a refusal.
ACCOUNT_OUT = '<a href="/signin">Sign in</a>'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass                                    # a quiet fixture

    def do_GET(self):
        if self.path.startswith("/img"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            width = int(q.get("w", ["1024"])[0])
            height = int(q.get("h", ["1536"])[0])
            # A seed, so the render and the uploaded reference can be the same SIZE
            # (which is the trap) while still being different IMAGES (so a test can
            # tell which one got saved). Without it they are byte-identical and the
            # decoy assertion cannot fail even when the driver is wrong.
            seed = int(q.get("seed", ["7"])[0])
            body = png(width, height, seed=seed)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        signed_out = "scenario=signedout" in self.path
        body = PAGE.replace("__ACCOUNT__",
                            ACCOUNT_OUT if signed_out else ACCOUNT_IN).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(port=0):
    """Start the fixture on a background thread. Returns (server, port)."""
    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_port


if __name__ == "__main__":                                       # pragma: no cover
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server, port = serve(port)
    print(f"fixture Gemini on http://127.0.0.1:{port}/?scenario=ok")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
