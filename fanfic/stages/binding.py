"""Stage 7 — Binding. Assemble accepted chapters, images, front matter, and a cover
into a validated `.epub`.

DEVIATION FROM THE ORIGINAL DESIGN, stated plainly: the design specified pandoc.
This builds the epub in pure Python instead. An epub *is* a structured zip —
mimetype, container, an OPF manifest and spine, an epub3 nav document, xhtml per
chapter, embedded images — and a hand-built one is fully deterministic and testable
with no external binary, where a pandoc call is neither. If the mini ever wants
pandoc's typography, `build_epub` is the one function to swap; `validate_epub` is
unchanged either way.

Assembly is stage-then-atomic and validation happens BEFORE the rename, so a book is
never "bound" until the artifact has been proven to open. Verify before commit.
"""

import html
import re
import zipfile
from xml.etree import ElementTree as ET

from .. import paths
from ..gates import segments
from ..infra import storage
from ..models import images

_CSS = ("body{font-family:Georgia,serif;line-height:1.5;margin:5%}"
        "h1{text-align:center}"
        # A titled chapter heading reads as two lines: a small caps number over the
        # title itself. Reflowable-safe — no fixed sizes, no floats.
        ".chapter-title{margin-bottom:2em}"
        ".chapter-number{display:block;font-size:.7em;font-weight:normal;"
        "letter-spacing:.18em;text-transform:uppercase;opacity:.65;"
        "margin-bottom:.4em}"
        ".chapter-name{display:block;font-size:1em}"
        # Scale every illustration to the reader's width so nothing overflows a
        # phone, centre it, and cap it so a large source image is not blown up past
        # its native size on a wide (iPad) screen.
        "img{max-width:100%;height:auto;display:block;margin:1em auto}"
        "figure{margin:1.5em 0;text-align:center}"
        # The scene break between two settings, where no illustration already marks it.
        ".scene-break{text-align:center;margin:1.6em 0;letter-spacing:.6em;"
        "text-indent:.6em;opacity:.6}"

        # --- The cover ------------------------------------------------------
        #
        # A cover is the one page in the book that is not reflowable text, so it gets
        # the one set of rules that fights the defaults above: no page margin, the art
        # filling the whole page, and the title typeset ON it.
        #
        # The title is HTML rather than part of the generated picture, and that is
        # deliberate. Image models cannot letter — this project has three reference
        # sheets that came back captioned in spite of the prompt forbidding text, and
        # every image prompt in the pipeline now ends by banning lettering outright.
        # So the art stays wordless and the typography is done here, where it is
        # actually typography: real kerning, a real typeface, the right size at any
        # screen width, and legible over whatever the picture turned out to be.
        ".cover-body{margin:0;padding:0}"
        ".cover{position:relative;margin:0;padding:0;width:100%;height:100vh;"
        "min-height:100%;overflow:hidden;background:#12101a}"
        # `cover` rather than `contain`: the page is filled edge to edge whatever the
        # reader's aspect ratio is. The art is generated 2:3, so on a normal e-reader
        # page the crop is a few percent off the long edge and nothing composed near
        # the centre is ever lost.
        ".cover-art{position:absolute;top:0;left:0;width:100%;height:100%;"
        "max-width:none;margin:0;object-fit:cover;object-position:center}"
        # A scrim, not a box. It fades from opaque at the top edge to nothing a third
        # of the way down, so the title always has something to sit against no matter
        # how bright the art is underneath, without stamping a rectangle on the
        # picture. The cover prompt asks for clear space at the top to land in.
        ".cover-plate{position:absolute;top:0;left:0;right:0;padding:9% 8% 12% 8%;"
        "text-align:center;"
        "background:linear-gradient(to bottom,rgba(8,6,14,.82) 0%,"
        "rgba(8,6,14,.62) 55%,rgba(8,6,14,0) 100%)}"
        ".cover-title{margin:0;font-size:2.6em;line-height:1.1;font-weight:700;"
        "letter-spacing:.02em;color:#fff;"
        "text-shadow:0 2px 12px rgba(0,0,0,.85),0 0 2px rgba(0,0,0,.9)}"
        ".cover-rule{width:22%;margin:.7em auto;border:0;border-top:2px solid "
        "rgba(255,255,255,.75)}"
        ".cover-author{margin:0;font-size:1em;letter-spacing:.22em;"
        "text-transform:uppercase;color:rgba(255,255,255,.92);"
        "text-shadow:0 2px 10px rgba(0,0,0,.85)}")

_CONTAINER_XML = (
    '<?xml version="1.0"?>\n'
    '<container version="1.0" '
    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
    '  <rootfiles><rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles>\n'
    '</container>\n')


def _md_to_xhtml_body(md_text):
    """A very small Markdown -> XHTML: blank-line-separated paragraphs, escaped. The
    drafting prompt constrains output to plain prose, so this stays deliberately
    minimal rather than becoming a Markdown engine. If chapters ever start using
    richer Markdown, this is what has to grow."""
    out = []
    for block in re.split(r"\n\s*\n", md_text.strip()):
        block = block.strip()
        if block:
            out.append("<p>" + html.escape(block).replace("\n", "<br/>") + "</p>")
    return "\n".join(out) or "<p></p>"


def _xhtml_page(title, body, body_class=""):
    css_class = f' class="{body_class}"' if body_class else ""
    return (f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" '
            f'xmlns:epub="http://www.idpf.org/2007/ops">\n'
            f'<head><title>{html.escape(title)}</title>'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"/>'
            f'<link rel="stylesheet" type="text/css" href="../style.css"/></head>\n'
            f'<body{css_class}>{body}</body>\n</html>\n')


def _rendered_slots(sid, book_num, chapter_num):
    """Which image slots for one chapter actually have a file on disk, in order.

    Read off the directory rather than counted up to a configured maximum. The number
    of pictures a chapter gets is now the number of times it changes scene, bounded by
    the run's remaining picture budget — so there is no constant to scan to, and a
    binder that scanned to one would silently drop everything past it."""
    directory = paths.images_dir(sid, book_num)
    if not directory.exists():
        return []
    found = []
    for image in directory.glob(f"ch{int(chapter_num):02d}_*.png"):
        try:
            found.append(int(image.stem.split("_")[-1]))
        except ValueError:
            continue
    return sorted(found)


def _media_type(blob):
    """What to declare in the manifest for a picture, read from its own header.

    The files are all named `.png` and the pictures are usually JPEG, because that is
    what Gemini returns. Declaring the extension rather than the content produces an
    epub that says `image/png` over JPEG bytes — invalid, and refused by strict
    readers. Falls back to `image/png` only when the header is unrecognisable, which
    the sanity floor should already have prevented from reaching disk."""
    return images.mime_of(blob) or "image/png"


def _figure(sid, book_num, chapter_num, k, files, manifest):
    """Embed one accepted scene image and return its figure markup."""
    img = paths.scene_image_path(sid, book_num, chapter_num, k)
    rel = f"images/ch{chapter_num:02d}_{k}.png"
    blob = img.read_bytes()
    files[f"OEBPS/{rel}"] = blob
    manifest.append((f"img-{chapter_num:02d}-{k}", rel, _media_type(blob), ""))
    return (f'\n<figure><img src="../{rel}" '
            f'alt="chapter {chapter_num} scene {k}"/></figure>')


def _chapter_body(sid, book_num, chapter_num, prose, files, manifest):
    """One chapter's prose and pictures, with each picture at the end of its own scene.

    This is the placement change. Every figure used to be concatenated after the
    chapter's last paragraph — the only placement this binder has ever had — so a
    reader met the dinner scene twelve pages after the dinner. The writer now marks
    every change of place or time, an image slot number *is* a scene segment number,
    and a picture is printed where the scene it shows ends.

    Slot `k` belongs to segment `k`, and anything past the last segment falls to the
    end of the chapter. That total rule is what makes a chapter delivered without
    break lines degrade to the old behaviour instead of losing its pictures."""
    parts = segments.split(prose) or [""]
    slots = _rendered_slots(sid, book_num, chapter_num)
    body = ""
    for index, part in enumerate(parts, 1):
        body += _md_to_xhtml_body(part)
        figures = [k for k in slots if min(k, len(parts)) == index]
        for k in figures:
            body += _figure(sid, book_num, chapter_num, k, files, manifest)
        # A scene change the reader can see. The markers are stripped by the splitter,
        # so without this a chapter whose budget ran to two pictures would take the
        # reader from the kitchen at dinner to a clearing the next morning mid-page
        # with nothing between the paragraphs — the split removed the separator that
        # used to survive into the epub as an ordinary paragraph.
        #
        # An illustration IS the separator where there is one, so the ornament only
        # appears at a boundary that has no picture, and never after the last segment.
        if index < len(parts) and not figures:
            body += '\n<p class="scene-break">* * *</p>'
    return body


def _cover_page(title, author):
    """The cover: the art filling the page, with the title typeset over it.

    Both halves of that were missing. The art was an ordinary inline image inheriting
    the body's 5% page margin and the `max-width:100%` rule every illustration gets, so
    on anything wider than the picture it sat in the middle of a white page with a
    border round it — a picture *of* a cover rather than a cover. And the book's own
    title appeared nowhere on it, because the one place it could have come from is
    lettering drawn by the image model, which is the one thing every image prompt in
    this project explicitly forbids for good reason.

    So the page is its own layout: no margin, the image absolutely positioned and
    covering, and the title set in real type over a gradient scrim that guarantees
    contrast whatever the art underneath turned out to be.

    A long title is what breaks a cover, so the size steps down as it gets longer
    rather than overflowing the plate or being shrunk to nothing."""
    length = len(title)
    size = "2.6em" if length <= 24 else "2.1em" if length <= 40 else "1.7em"
    body = (
        '<div class="cover">'
        '<img class="cover-art" src="../images/cover.png" alt=""/>'
        '<div class="cover-plate">'
        f'<h1 class="cover-title" style="font-size:{size}">{html.escape(title)}</h1>'
        '<hr class="cover-rule"/>'
        f'<p class="cover-author">{html.escape(author)}</p>'
        '</div></div>')
    return _xhtml_page(title, body, body_class="cover-body")


def _chapter_heading(chapter, n):
    """The chapter's on-page heading and its table-of-contents label.

    Returns `(heading_html, nav_label)`. Uses the outline's `title` when there is one,
    and degrades to a bare "Chapter N" when there is not.

    Both halves matter. The outline prompt never asked for titles, the structure gate
    never required them, and this function used to hardcode `f"Chapter {n}"` — three
    independent places dropping the same field, so the first book was heading for 37
    numbered chapters and nobody would have known until they opened the epub. The
    prompt and the gate are fixed, but the fallback stays: an outline generated before
    that fix is durable state, and a book that reads slightly plainer beats a binder
    that refuses to build."""
    title = str(chapter.get("title") or "").strip()
    if not title:
        return f"<h1>Chapter {n}</h1>\n", f"Chapter {n}"
    safe = html.escape(title)
    return (f'<h1 class="chapter-title">'
            f'<span class="chapter-number">Chapter {n}</span>'
            f'<span class="chapter-name">{safe}</span></h1>\n',
            f"Chapter {n}: {title}")


def build_epub(series_rec, book_num, title, author="Fanfiction-Writer"):
    """Assemble, validate, and atomically place the book's epub. Returns the final
    path. Raises RuntimeError if a chapter is missing or validation fails — in which
    case nothing is placed and the book is not BOUND."""
    sid = series_rec["series_id"]
    outline = storage.load_json(paths.outline_path(sid, book_num), {"chapters": []})
    chapters = outline.get("chapters", [])

    manifest, spine, files = [], [], {}
    files["mimetype"] = b"application/epub+zip"
    files["META-INF/container.xml"] = _CONTAINER_XML.encode("utf-8")
    files["OEBPS/style.css"] = _CSS.encode("utf-8")

    # Cover, if one was rendered. Binding never assumes it: a text-only build has
    # none by design, and this function is also called on a partly-drawn book by the
    # tests. A book reaching BINDING through the engine has one.
    cover = paths.cover_path(sid, book_num)
    cover_id = None
    if cover.exists():
        cover_id = "cover-img"
        cover_bytes = cover.read_bytes()
        files["OEBPS/images/cover.png"] = cover_bytes
        manifest.append((cover_id, "images/cover.png", _media_type(cover_bytes),
                         ' properties="cover-image"'))
        files["OEBPS/text/cover.xhtml"] = _cover_page(title, author).encode("utf-8")
        manifest.append(("cover-page", "text/cover.xhtml",
                         "application/xhtml+xml", ""))
        spine.append("cover-page")

    # Title page.
    files["OEBPS/text/title.xhtml"] = _xhtml_page(
        title, f"<h1>{html.escape(title)}</h1>"
               f"<p style='text-align:center'>{html.escape(author)}</p>"
    ).encode("utf-8")
    manifest.append(("title-page", "text/title.xhtml", "application/xhtml+xml", ""))
    spine.append("title-page")

    # Chapters and their scene images.
    nav_items = []
    for chapter in chapters:
        n = chapter["number"]
        prose_path = paths.chapter_path(sid, book_num, n)
        if not prose_path.exists():
            raise RuntimeError(
                f"binding: accepted chapter {n} missing at {prose_path}")
        heading, nav_label = _chapter_heading(chapter, n)
        body = heading + _chapter_body(
            sid, book_num, n, prose_path.read_text(encoding="utf-8"),
            files, manifest)
        cid = f"ch{n:02d}"
        files[f"OEBPS/text/{cid}.xhtml"] = _xhtml_page(
            nav_label, body).encode("utf-8")
        manifest.append((cid, f"text/{cid}.xhtml", "application/xhtml+xml", ""))
        spine.append(cid)
        nav_items.append((cid, nav_label))

    # epub3 navigation document.
    nav_lis = "\n".join(
        f'      <li><a href="text/{cid}.xhtml">{html.escape(label)}</a></li>'
        for cid, label in nav_items)
    files["OEBPS/nav.xhtml"] = _xhtml_page(
        "Contents",
        f'<nav epub:type="toc" id="toc"><h1>Contents</h1>\n'
        f'    <ol>\n{nav_lis}\n    </ol></nav>').encode("utf-8")
    manifest.append(("nav", "nav.xhtml", "application/xhtml+xml", ' properties="nav"'))

    # OPF package document.
    manifest_xml = "\n".join(
        f'    <item id="{mid}" href="{href}" media-type="{mt}"{extra}/>'
        for mid, href, mt, extra in manifest)
    spine_xml = "\n".join(f'    <itemref idref="{ref}"/>' for ref in spine)
    meta_cover = f'\n    <meta name="cover" content="{cover_id}"/>' if cover_id else ""
    files["OEBPS/content.opf"] = (
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        f'unique-identifier="bookid">\n'
        f'  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="bookid">urn:fanfic:{sid}:book{book_num}'
        f'</dc:identifier>\n'
        f'    <dc:title>{html.escape(title)}</dc:title>\n'
        f'    <dc:language>en</dc:language>\n'
        f'    <dc:creator>{html.escape(author)}</dc:creator>{meta_cover}\n'
        f'  </metadata>\n'
        f'  <manifest>\n{manifest_xml}\n  </manifest>\n'
        f'  <spine>\n{spine_xml}\n  </spine>\n'
        f'</package>\n').encode("utf-8")

    # mimetype must be the first entry and stored uncompressed.
    dest = paths.epub_path(sid, book_num, title)
    staged = storage.staging_dir_for(dest.parent) / dest.name
    with zipfile.ZipFile(staged, "w") as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, files.pop("mimetype"))
        for name, data in files.items():
            zf.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)

    validate_epub(staged)                    # verify BEFORE placing
    storage.atomic_place(staged, dest)
    return dest


def validate_epub(path):
    """Confirm a built epub is well-formed: opens as a zip, mimetype stored and
    first, the OPF resolves, every manifest item is embedded, every spine item
    exists. Raises RuntimeError on any failure."""
    if not zipfile.is_zipfile(path):
        raise RuntimeError(f"epub is not a valid zip: {path}")
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        if not names or names[0] != "mimetype":
            raise RuntimeError("epub: mimetype is not the first entry")
        if zf.getinfo("mimetype").compress_type != zipfile.ZIP_STORED:
            raise RuntimeError("epub: mimetype must be stored uncompressed")
        if zf.read("mimetype") != b"application/epub+zip":
            raise RuntimeError("epub: wrong mimetype bytes")
        if "META-INF/container.xml" not in names:
            raise RuntimeError("epub: missing container.xml")

        container = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile = container.find(
            ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
        opf_path = rootfile.get("full-path")
        if opf_path not in names:
            raise RuntimeError(f"epub: OPF {opf_path} not in archive")

        opf = ET.fromstring(zf.read(opf_path))
        ns = {"opf": "http://www.idpf.org/2007/opf"}
        base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
        ids = {}
        for item in opf.findall(".//opf:manifest/opf:item", ns):
            href = item.get("href")
            ids[item.get("id")] = href
            if base + href not in names:
                raise RuntimeError(f"epub: manifest item {href} not embedded")
        spine = opf.findall(".//opf:spine/opf:itemref", ns)
        if not spine:
            raise RuntimeError("epub: empty spine")
        for ref in spine:
            if ref.get("idref") not in ids:
                raise RuntimeError(
                    f"epub: spine references unknown id {ref.get('idref')}")
    return True
