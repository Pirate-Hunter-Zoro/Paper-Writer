"""Real reference art — the source material's own pictures, as render references.

Every previous attempt at visual fidelity in this project has been a *description*: a
locked appearance in prose, quoted into the prompt, and a generated model sheet built
from that prose. It got identity roughly right and proportion consistently wrong — a
seventeen-year-old drawn as a young adult, his twin sister drawn as a child, both from
the same two sentences. Prose cannot pin a face. There is no wording for "this exact
jaw", and the more words you spend trying, the more the model averages.

So this stage fetches the actual character art from the source wikis and hands it to
the image model as reference input. A picture of Dipper Pines settles Dipper Pines's
face in a way no paragraph does, and it settles proportion, age and silhouette at the
same time — which is the failure the descriptions could not reach.

Fandom's MediaWiki API is the source: it is public, it is stable, it needs no key, and
it is where these images already live for exactly this purpose. Nothing is republished
— the files sit in the gitignored state tree and are used as conditioning input for a
personal fan work, the same way an artist works from a model sheet on the desk beside
them.

Stdlib only, like everything else here.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .. import config, paths
from ..infra import storage

_UA = "Fanfiction-Writer/1.0 (reference lookup; personal fan project)"
_TIMEOUT = 25

# Files that are on a character page and are never that character.
_JUNK = re.compile(
    r"(wiki|logo|icon|nav|banner|button|placeholder|site-|favicon|spoiler|"
    r"stub|template|badge|award|poll|gallery-|category|signature|symbol|"
    r"emblem|sigil|cursor|background)", re.I)
_USABLE = re.compile(r"\.(png|jpe?g|webp)$", re.I)

# Fandom serves WebP under a .png URL through content negotiation, so what a file is
# called says nothing about what arrives. Sniff the bytes.
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)


def _extension(blob):
    for magic, suffix in _MAGIC:
        if blob.startswith(magic):
            return suffix
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return ".webp"
    return None


def _get(url, params=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read()


def _api(host, params):
    params = dict(params, format="json")
    return json.loads(_get(f"https://{host}/api.php", params))


def candidate_hosts(universe):
    """Fandom subdomains worth trying for a universe name, best guess first.

    A resolver rather than a lookup table on purpose: this project is supposed to write
    a novel in any universe you name, and a hardcoded map of four wikis is a system that
    works for four fandoms."""
    words = re.findall(r"[A-Za-z0-9]+", universe.lower())
    joined = "".join(words)
    no_articles = "".join(w for w in words if w not in ("the", "a", "of", "and"))
    # "She-Ra and the Princesses of Power" -> sheraandtheprincessesofpower, sherra…
    first_two = "".join(words[:2])
    return list(dict.fromkeys(h for h in (joined, no_articles, first_two, words[0])
                              if h))


def resolve_host(universe, log_fn=None):
    """The Fandom host that actually answers for this universe, or None."""
    for host in (f"{c}.fandom.com" for c in candidate_hosts(universe)):
        try:
            data = _api(host, {"action": "query", "meta": "siteinfo"})
            if data.get("query", {}).get("general"):
                if log_fn:
                    log_fn(f"reference art: {universe} -> {host}")
                return host
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            continue
    if log_fn:
        log_fn(f"reference art: no wiki found for {universe!r}; "
               f"tried {candidate_hosts(universe)}")
    return None


def _words(text):
    return {w.lower() for w in re.findall(r"[A-Za-z]+", text) if len(w) > 2}


def resolve_title(host, name):
    """The wiki's own title for a character, or **None when this wiki does not have
    them**. That second half is the whole contract.

    A series bible says "Stanford Pines" and "Stanley Pines"; the Gravity Falls wiki
    files them under "Ford Pines" and "Stan Pines", so an exact-title lookup returns
    nothing for two of the book's principals. Search fixes that and introduces a far
    worse failure in its place: **a wiki search never returns nothing.** Asked for
    "Waddles", the Owl House wiki answers "Dee Bradley Baker" — the voice actor's page.
    Asked for "Perfuma" it answers "Luz Noceda". Taking the top hit means a pig is
    anchored to a photograph of a man and a flower princess is anchored to Luz, and
    nothing anywhere says so: the pictures simply come out wrong in a way that reads as
    the image model being bad at its job.

    So a hit has to earn the character. An exact title wins; otherwise the hit must
    share a real word with the name. A `Waddles/Gallery` subpage resolves to its base
    article, because the infobox portrait — the single best reference on any wiki — is
    on the article and not on the gallery. Nothing plausible means **None**, and no art
    is unambiguously better than another show's art: without it a sheet falls back to
    the locked prose description, which is merely imprecise rather than actively
    depicting somebody else."""
    try:
        data = _api(host, {"action": "query", "list": "search",
                           "srsearch": name, "srlimit": 5})
        hits = [h["title"] for h in data.get("query", {}).get("search", [])]
    except Exception:                                             # noqa: BLE001
        return None
    wanted = _words(name)
    if not wanted:
        return None
    for hit in hits:
        base = hit.split("/")[0].strip()
        if base.lower() == name.lower():
            return base
    for hit in hits:
        base = hit.split("/")[0].strip()
        if wanted & _words(base):
            return base
    return None


def hosts_for_character(origin, universes, log_fn=None):
    """The wikis to look a character up on, THEIRS first.

    The bible records which show each character comes from, and putting it at the head
    of the list is what keeps a Gravity Falls pig off the Owl House wiki. Without it
    the fetcher walked the series' universes in order and kept whichever answered
    first — and since a wiki search always answers, that is the same wiki for every
    character in the book.

    The rest of the series still follows, because an origin can be missing: this
    book's bible has a canon Amphibia character with no origin recorded at all, and
    stopping at the first wiki that merely *resolves* left him with nothing. Trying the
    others is safe now, and only now, because `resolve_title` refuses a hit that has
    not earned the name — the order is a preference, and the matcher is the guard."""
    ordered = [u for u in ([origin] if origin else []) + list(universes or []) if u]
    hosts = []
    for universe in dict.fromkeys(ordered):
        host = resolve_host(universe, log_fn=log_fn)
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def _page_images(host, title, limit):
    """Image file titles on a page, most likely to be the character first.

    `pageimages` gives the infobox picture, which is nearly always the best single
    reference; `images` gives everything else on the page, which is a mixed bag of
    screenshots, and screenshots of the character in motion are exactly what a
    reference wants."""
    out = []
    try:
        data = _api(host, {"action": "query", "titles": title,
                           "prop": "pageimages", "pithumbsize": 900})
        for page in data.get("query", {}).get("pages", {}).values():
            src = (page.get("thumbnail") or {}).get("source")
            if src:
                out.append(src)
    except Exception:                                             # noqa: BLE001
        pass

    try:
        data = _api(host, {"action": "query", "titles": title, "prop": "images",
                           "imlimit": 60})
        names = [i["title"] for page in data.get("query", {}).get("pages", {}).values()
                 for i in page.get("images", [])
                 if _USABLE.search(i["title"]) and not _JUNK.search(i["title"])]
        for batch in (names[i:i + 20] for i in range(0, len(names), 20)):
            info = _api(host, {"action": "query", "titles": "|".join(batch),
                               "prop": "imageinfo", "iiprop": "url|size"})
            for page in info.get("query", {}).get("pages", {}).values():
                for item in page.get("imageinfo", []):
                    if item.get("width", 0) >= 300:
                        out.append(item["url"])
    except Exception:                                             # noqa: BLE001
        pass
    return list(dict.fromkeys(out))[:limit]


def fetch_for_character(host, name, dest_dir, limit=None, log_fn=None):
    """Download up to `limit` reference pictures for one character. Returns paths."""
    limit = limit or config.REF_IMAGES_PER_CHARACTER
    dest_dir.mkdir(parents=True, exist_ok=True)
    existing = _on_disk(dest_dir)
    if existing:
        return existing[:limit]

    saved = []
    title = resolve_title(host, name)
    if title is None:
        if log_fn:
            log_fn(f"reference art: {host} has no page that is plausibly {name!r}; "
                   f"taking nothing rather than another character's pictures")
        return []
    if title != name and log_fn:
        log_fn(f"reference art: {name} is filed as {title!r} on this wiki")
    for url in _page_images(host, title, limit * 3):
        if len(saved) >= limit:
            break
        try:
            blob = _get(url)
        except (urllib.error.URLError, OSError):
            continue
        # Guard against an HTML error page or a tracking pixel arriving as "an image".
        if len(blob) < 8000:
            continue
        suffix = _extension(blob)
        if suffix is None:
            continue
        out = dest_dir / f"ref{len(saved) + 1}{suffix}"
        out.write_bytes(blob)
        saved.append(out)
    if log_fn:
        log_fn(f"reference art: {name} -> {len(saved)} picture(s)")
    return saved


def _miss_marker(dest_dir):
    """Sidecar recording that this wiki genuinely had nothing for a character.

    Distinct from an empty directory, which means "not looked yet". Without it a
    character with no page is re-searched across four wikis on every cycle forever, for
    an answer that will not change — rude to the wikis and slow for us. `_on_disk`
    ignores it, so it can never be mistaken for art."""
    return dest_dir / ".no-source-art"


def ensure(series_rec, book_num, name, origin=None, log_fn=None):
    """Reference art for ONE character, fetched on first need. Never raises.

    This is where the gathering actually happens, and it is per-character and lazy on
    purpose. `gather` sweeps the bible in one pass, which is correct exactly once and
    then wrong forever: the cast of a crossover grows chapter by chapter as the bible
    merges new people in, so a book that swept its cast at planning time strands
    everybody introduced afterwards with no source art and nobody notices, because a
    sheet drawn from prose alone still looks like *a* character. Twenty-three of this
    book's cast were in exactly that state — including a pig drawn from the sentence
    "a pink pig, originally billed at fifteen pounds".

    Asking at the point of use means the question is asked once per character, at the
    moment their sheet is drawn, however late they join."""
    if (origin or "") == "original":
        return []                        # no source material exists, by definition
    sid = series_rec["series_id"]
    dest = paths.refart_dir(sid, book_num, name)
    existing = _on_disk(dest)
    if existing or _miss_marker(dest).exists():
        return existing

    try:
        got = []
        for host in hosts_for_character(origin, series_rec.get("universes", []),
                                        log_fn=log_fn):
            got = fetch_for_character(host, name, dest, log_fn=log_fn)
            if got:
                break
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        if log_fn:
            log_fn(f"reference art: lookup for {name} failed ({exc}); the sheet falls "
                   f"back to the written design and this is retried next cycle")
        return []
    if not got:
        dest.mkdir(parents=True, exist_ok=True)
        _miss_marker(dest).write_text(
            "no wiki page could be matched to this character", encoding="utf-8")
    return got


def gather(series_rec, book_num, log_fn=None):
    """Fetch reference art for every character in the bible. Idempotent and resumable.

    Best-effort throughout: a wiki that does not answer, a character with no page, a
    download that fails — none of them is worth stopping a book for, and the pipeline
    still has the locked prose description to fall back on."""
    sid = series_rec["series_id"]
    bible = storage.load_json(paths.series_bible_path(sid), {})
    found = {}
    characters = bible.get("characters") or {}
    for name in sorted(characters.keys()):
        # ORIGINALS ARE SKIPPED, and this is not an optimisation.
        #
        # An original has no source material by definition, so their locked appearance
        # is the whole anchor — which is why the plan gate demands a fuller one from
        # them. Looking one up anyway is not merely wasted: a wiki search always
        # answers, so an invented antagonist would be handed some real character's
        # pictures and every render of the new villain would be anchored to them.
        if (characters[name].get("origin") or "") == "original":
            if log_fn:
                log_fn(f"reference art: {name} is original to this book — no wiki "
                       f"lookup; their sheet is drawn from the written design alone")
            continue
        got = ensure(series_rec, book_num, name,
                     origin=characters[name].get("origin"), log_fn=log_fn)
        if got:
            found[name] = got
    if log_fn:
        log_fn(f"reference art: {len(found)}/{len(characters)} characters have source "
               f"pictures")
    return found


def _on_disk(d):
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir()
                  if p.name.startswith("ref") and p.suffix.lower()
                  in (".png", ".jpg", ".jpeg", ".webp", ".gif"))


def for_character(series_id, book_num, name):
    """Reference pictures on disk for one character. Never raises."""
    return _on_disk(paths.refart_dir(series_id, book_num, name))


def confirmed_missing(series_id, book_num, name):
    """Whether a lookup has actually run and found this character has no page.

    The distinction that matters is between "the wikis do not have them" and "the
    network was down when we asked". Only the first is an answer, and only the first
    should stop anyone retrying."""
    return _miss_marker(paths.refart_dir(series_id, book_num, name)).exists()
