import json
import os
import re
import base64
import urllib.parse
from datetime import datetime
from html import escape, unescape

ROOT = os.path.dirname(os.path.dirname(__file__))
SITE_DIR = os.path.join(ROOT, "site")
DOCS_PATH = os.path.join(SITE_DIR, "docs.json")
BROWSE_DIR = os.path.join(SITE_DIR, "browse")
MSG_HTML_DIR = os.path.join(SITE_DIR, "msg")  # per-message HTML alongside JSON
OUT_BY_YEAR_DIR = os.path.join(ROOT, "out", "by_year")

# replace any messy NAV include with a robust loader that finds nav-include.js from pages at different depths
NAV_INCLUDE_SNIPPET = (
    '<div id="nav-placeholder"></div>'
    '<script>(function(){'
    'const candidates=[\'./nav-include.js\',\'../nav-include.js\',\'../../nav-include.js\'];'
    'function tryLoad(i){if(i>=candidates.length) return;'
    'const s=document.createElement(\"script\");s.src=candidates[i];'
    's.onerror=function(){tryLoad(i+1)};'
    'document.head.appendChild(s);}tryLoad(0);'
    '})();</script>'
)

def ensure_dir(p):
    os.makedirs(p, exist_ok=True)

def get_year(doc):
    # prefer explicit year field, fallback to parsing date, else "unknown"
    if isinstance(doc.get("year"), (int, str)):
        return str(doc["year"])
    date = doc.get("date") or doc.get("datetime") or doc.get("created")
    if not date:
        return "unknown"
    # try ISO first
    try:
        dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
        return str(dt.year)
    except Exception:
        # fallback: find 4-digit year
        m = re.search(r"(19|20)\d{2}", str(date))
        return m.group(0) if m else "unknown"

def pick_text(doc):
    # prefer explicit full_text/index_text/html-like fields, unescape HTML entities
    priority_keys = (
        "full_text",
        "index_text",
        "html",
        "body",
        "body_html",
        "text_html",
        "text",
        "content",
        "body_text",
        "plain",
        "plain_text",
        "payload",
        "message",
        "raw",
        "source",
    )

    for k in priority_keys:
        v = doc.get(k)
        if isinstance(v, str) and v.strip():
            vv = unescape(v)
            # treat as HTML if it contains tags after unescaping
            if re.search(r"<\/?\w+>", vv):
                return "html", vv
            return "text", vv

    # recursive fallback: find first non-empty string value, unescape and check for HTML
    def recurse(o):
        if isinstance(o, str):
            s = o.strip()
            if not s:
                return None
            s_un = unescape(s)
            if re.search(r"<\/?\w+>", s_un):
                return ("html", s_un)
            return ("text", s_un)
        if isinstance(o, dict):
            # iterate values in insertion order (json load preserves order)
            for v in o.values():
                r = recurse(v)
                if r:
                    return r
        if isinstance(o, list):
            for v in o:
                r = recurse(v)
                if r:
                    return r
        return None

    res = recurse(doc)
    return res or (None, "")

# add missing helpers used elsewhere in the script
def _norm_id(v):
    if v is None:
        return None
    s = str(v).strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    return s

def _try_decode_base64_heuristic(text):
    """Try to decode an entire string if it's raw base64; return decoded string or None."""
    if not isinstance(text, str):
        return None
    s = re.sub(r"\s+", "", text)
    # heuristic: reasonably long base64-like string and no illegal chars
    if len(s) < 16 or re.search(r"[^A-Za-z0-9+/=]", s):
        return None
    try:
        raw = base64.b64decode(s, validate=True)
        try:
            return raw.decode("utf-8")
        except Exception:
            return raw.decode("latin-1", errors="replace")
    except Exception:
        return None

def _decode_base64_mime(text):
    """Find MIME parts marked base64, decode them, and return (combined_text, any_html_flag).
    Returns None if no base64 MIME parts found.
    """
    if not isinstance(text, str):
        return None
    any_html = False
    parts = []
    pos = 0
    found = False
    while True:
        m = re.search(r"Content-Transfer-Encoding:\s*base64", text[pos:], flags=re.I)
        if not m:
            break
        found = True
        header_idx = pos + m.start()
        after_header = pos + m.end()
        # find first blank line after header
        dbl = re.search(r"\r?\n\r?\n", text[after_header:])
        payload_start = after_header + (dbl.end() if dbl else 0)
        # find next MIME boundary (line starting with --) or end of text
        b = re.search(r"\r?\n--[^\r\n]+", text[payload_start:])
        payload_end = payload_start + b.start() if b else len(text)
        payload = text[payload_start:payload_end].strip()

        # try to find a Content-Type header before this header (since headers precede encoding)
        prev_boundary = text.rfind("\n--", 0, header_idx)
        look_start = prev_boundary if prev_boundary != -1 else 0
        ct_section = text[look_start:header_idx]
        ct_match = re.search(r"Content-Type:\s*([^\r\n;]+)", ct_section, flags=re.I)
        ctype = (ct_match.group(1).lower() if ct_match else "")

        b64 = re.sub(r"\s+", "", payload)
        try:
            raw = base64.b64decode(b64, validate=True)
            try:
                decoded = raw.decode("utf-8")
            except Exception:
                decoded = raw.decode("latin-1", errors="replace")
            parts.append(decoded)
            if "html" in ctype:
                any_html = True
        except Exception:
            # if payload isn't valid base64, keep original block
            parts.append(payload)

        pos = payload_end

    if not found:
        return None
    return ("\n\n".join(parts), any_html)

def compute_mid(doc):
    """Compute the stable filename/id used by the generator for a message dict."""
    for k in ("id", "_id", "message-id", "message_id", "msgid", "mid"):
        v = doc.get(k)
        if v:
            s = str(v).strip()
            if s.startswith("<") and s.endswith(">"):
                s = s[1:-1].strip()
            return s
    # fallback stable id
    return "msg-" + str(abs(hash((doc.get("subject", ""), str(doc.get("date", ""))))))

def _norm_msgid(v):
    if v is None:
        return None
    s = str(v).strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    return s

def _split_references(refs):
    """Return normalized list of message-ids parsed from a References-like value."""
    if not refs:
        return []
    if isinstance(refs, list):
        items = refs
    else:
        items = re.findall(r"<[^>]+>|[^,\s]+", str(refs))
    return [_norm_msgid(x) for x in items if x and _norm_msgid(x)]

def load_out_index():
    """Scan out/by_year/*.ndjson and return a mapping of candidate ids -> full message dicts."""
    index = {}
    if not os.path.isdir(OUT_BY_YEAR_DIR):
        print("out/by_year directory not found:", OUT_BY_YEAR_DIR)
        return index

    total_files = 0
    total_lines = 0
    total_indexed = 0
    for fn in os.listdir(OUT_BY_YEAR_DIR):
        if not fn.endswith(".ndjson"):
            continue
        total_files += 1
        path = os.path.join(OUT_BY_YEAR_DIR, fn)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    total_lines += 1
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    # gather candidate id values and several stringified forms
                    seen_keys = set()
                    for k in ("id", "_id", "message-id", "message_id", "msgid", "mid"):
                        v = obj.get(k)
                        n = _norm_id(v)
                        if n and n not in seen_keys:
                            index[n] = obj
                            seen_keys.add(n)
                        # also add plain str() form and integer-string form if possible
                        if v is not None:
                            sval = str(v)
                            if sval and sval not in seen_keys:
                                index[sval] = obj
                                seen_keys.add(sval)
                            try:
                                ival = int(v)
                                sival = str(ival)
                                if sival not in seen_keys:
                                    index[sival] = obj
                                    seen_keys.add(sival)
                            except Exception:
                                pass
                    # also map subject+date hash as fallback
                    subj = obj.get("subject", "")
                    date = obj.get("date", "") or obj.get("datetime", "")
                    if subj or date:
                        key = "hash:" + str(abs(hash((subj, date))))
                        index[key] = obj
                    total_indexed += 1
        except Exception as e:
            print("error reading", path, e)
            continue

    print(f"Loaded out/by_year: files={total_files} lines={total_lines} indexed_items={len(index)} (entries scanned={total_indexed})")
    return index

# --- Thread helpers -------------------------------------------------------
def _thread_key_from_doc(doc):
    # prefer explicit thread-id
    for k in ("thread-id", "thread_id", "thread"):
        if doc.get(k):
            return str(doc.get(k))
    # prefer the first reference if present
    refs = doc.get("references") or doc.get("References")
    if refs:
        lst = _split_references(refs)
        if lst:
            return lst[0]
    # fallback to in-reply-to
    irt = doc.get("in-reply-to") or doc.get("in_reply_to") or doc.get("In-Reply-To")
    if irt:
        return _norm_msgid(irt) or None
    # else use message-id as thread root
    mid = doc.get("message-id") or doc.get("message_id") or doc.get("msgid") or doc.get("id")
    return _norm_msgid(mid) or None

# --- Add author helpers here (MOVED ABOVE main) ----------------------------
def _author_name_from_doc(doc):
    """Return a reasonable author/display name for a message dict (falls back to 'Unknown')."""
    for k in ("author", "from", "sender", "owner", "uploader", "author_name", "displayName"):
        v = doc.get(k)
        if v and isinstance(v, str) and v.strip():
            return v.strip()
    # try to parse "Name <email@domain>" patterns
    frm = doc.get("from") or doc.get("From")
    if isinstance(frm, str):
        m = re.match(r'\s*([^<]+)\s*<', frm)
        if m:
            return m.group(1).strip()
    return "Unknown"

def _slugify(s):
    """Create a filesystem-safe slug for author names."""
    if not s:
        return "unknown"
    s = s.lower().strip()
    s = re.sub(r"[<>\"']", "", s)
    s = re.sub(r"@", "-at-", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "unknown"
# --------------------------------------------------------------------------

def render_message_html(doc, prev_mid=None, next_mid=None):
    # id/subject
    sid = escape(str(doc.get("id", doc.get("_id", doc.get("message-id", "unknown")))))
    subject = doc.get("subject") or doc.get("title") or ""
    # if subject empty, try pulling a short text preview
    if not subject:
        # prefer full_text/index_text/plain first
        for k in ("full_text", "index_text", "text", "body", "content"):
            v = doc.get(k)
            if isinstance(v, str) and v.strip():
                subject = v.strip().splitlines()[0][:120]
                break
    subject = escape(str(subject or "No subject"))

    # sender: common keys
    sender_keys = ("author", "from", "sender", "uploader", "owner")
    sender_val = None
    for k in sender_keys:
        v = doc.get(k)
        if v:
            sender_val = v
            break
    sender = escape(str(sender_val or doc.get("author_name") or "Unknown"))

    # date: common keys, try to parse ISO-like timestamps
    date_keys = ("timestamp", "date", "datetime", "sent", "created", "time")
    raw_date = None
    for k in date_keys:
        v = doc.get(k)
        if v:
            raw_date = str(v)
            break
    pretty_date = ""
    if raw_date:
        try:
            # handle trailing Z
            dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            # show UTC-ish ISO string
            pretty_date = dt.strftime("%Y-%m-%d %H:%M:%S %z").strip()
        except Exception:
            # fall back to raw value
            pretty_date = raw_date
    pretty_date = escape(pretty_date)

    # body
    field, content = pick_text(doc)
    body_html = None

    # if content is raw html from pick_text, use as-is
    if field == "html" and isinstance(content, str) and content.strip():
        body_html = content
    else:
        # 1) try full-string base64 heuristic
        decoded_full = _try_decode_base64_heuristic(content)
        if decoded_full is not None:
            # if decoded looks like HTML, render as HTML
            if re.search(r"<\/?\w+>", decoded_full):
                body_html = decoded_full
            else:
                content = decoded_full
        else:
            # 2) try to decode MIME base64 parts
            dec = _decode_base64_mime(content)
            if dec:
                combined, any_html = dec
                if any_html:
                    body_html = combined
                else:
                    content = combined

    # final fallback: escape and show in <pre>
    if body_html is None:
        body_html = "<pre style='white-space:pre-wrap;'>" + escape(str(content)) + "</pre>"

    # Insert the clean nav placeholder (no diff markers) — shared site nav
    nav_html = NAV_INCLUDE_SNIPPET

    # Per-message navigation (chronological and thread links)
    nav_buttons = []
    if prev_mid:
        nav_buttons.append(f'<a href="../msg/{urllib.parse.quote(prev_mid)}.html">Prev</a>')
    if next_mid:
        nav_buttons.append(f'<a href="../msg/{urllib.parse.quote(next_mid)}.html">Next</a>')
    prev_thread = doc.get("_prev_in_thread")
    next_thread = doc.get("_next_in_thread")
    if prev_thread:
        nav_buttons.append(f'<a href="../msg/{urllib.parse.quote(prev_thread)}.html">Prev in thread</a>')
    if next_thread:
        nav_buttons.append(f'<a href="../msg/{urllib.parse.quote(next_thread)}.html">Next in thread</a>')
    local_nav_html = ("<p class='msg-nav'>" + " • ".join(nav_buttons) + "</p>") if nav_buttons else ""

    html = f"""<!doctype html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>{subject}</title>
    <style>
    body{{font-family:system-ui, -apple-system, "Segoe UI", Roboto, Arial; margin:0; padding:0; background:#fff;}}
    /* make the shared nav span the full viewport */
    #site-nav, #site-nav * {{ box-sizing: border-box; }}
    #site-nav {{ width:100%; display:block; }}
    /* keep page content centered in a container */
    .page-container {{ max-width:880px; margin:3rem auto; padding:0 1rem; }}
    header h1{{font-size:1.25rem;margin:0 0 .25rem 0}}
    header p{{color:#555; margin:.25rem 0 1rem 0}}
    .msg-body{{background:#fff; padding:1rem; border:1px solid #eee; border-radius:6px}}
    a.year-link{{display:inline-block; margin-right:.5rem}}
    .msg-nav{{margin:0 0 1rem 0;color:#444;font-size:0.95rem}}
    .msg-nav a{{color:#0366d6;text-decoration:none;margin-right:.5rem}}
    </style>
    </head>
    <body>
    {nav_html}
    <main class="page-container">
    <header>
    <h1>{subject}</h1>
    <p>From: {sender} • Date: {pretty_date}</p>
    </header>
    {local_nav_html}
    <article class="msg-body">
    {body_html}
    </article>
    </main>
    </body>
    </html>
    """
    return html

def main():
    if not os.path.exists(DOCS_PATH):
        print("docs.json not found at", DOCS_PATH)
        return
    ensure_dir(BROWSE_DIR)
    ensure_dir(MSG_HTML_DIR)
    with open(DOCS_PATH, "r", encoding="utf-8") as f:
        docs = json.load(f)
    # build index from out/by_year NDJSON to pull full message bodies
    ndjson_index = load_out_index()

    # build ordered list of mids (used to compute prev/next chronological)
    ordered_mids = [compute_mid(d) for d in docs]
    mid_to_index = {m: i for i, m in enumerate(ordered_mids)}

    # build a "full" doc list (prefer NDJSON/ndjson_index when available) for thread computation
    full_docs = []
    for d in docs:
        mid = compute_mid(d)
        rd = dict(d)
        # prefer ndjson_index entry if present (it likely contains full headers like references/in-reply-to)
        nd = None
        for k in (mid, _norm_msgid(d.get("message-id")), _norm_msgid(d.get("_id")), str(d.get("id"))):
            if not k:
                continue
            nd = ndjson_index.get(k)
            if nd:
                break
        if nd:
            rd.update(nd)
        full_docs.append((mid, rd))

    # group messages into threads using a thread-key heuristic and sort by date within each thread
    threads = {}
    for mid, rd in full_docs:
        tkey = _thread_key_from_doc(rd) or mid
        threads.setdefault(tkey, []).append((mid, rd))

    def _date_sort_key(item):
        _, rdoc = item
        for k in ("date", "datetime", "timestamp", "sent", "created", "time"):
            v = rdoc.get(k)
            if v:
                try:
                    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
                except Exception:
                    return str(v)
        return ""

    # sort each thread and build prev/next-in-thread maps
    prev_next_in_thread = {}
    for tkey, items in threads.items():
        # stable sort: if datetime parse failed we fall back to string ordering
        items_sorted = sorted(items, key=_date_sort_key)
        for i, (mid, rd) in enumerate(items_sorted):
            prev_mid_thread = items_sorted[i - 1][0] if i > 0 else None
            next_mid_thread = items_sorted[i + 1][0] if i < len(items_sorted) - 1 else None
            prev_next_in_thread[mid] = (prev_mid_thread, next_mid_thread)
            # also attach to rd so render_message_html can pick them up if we pass rd
            rd["_prev_in_thread"] = prev_mid_thread
            rd["_next_in_thread"] = next_mid_thread

    # write per-message HTML files
    written = 0
    missed_bodies = 0
    for doc in docs:
        # compute the stable filename/id for this message (used for linking & file naming)
        mid = compute_mid(doc)

        # if a per-message JSON exists (site/msg/<mid>.json), load it and prefer its content fields
        json_path = os.path.join(MSG_HTML_DIR, f"{mid}.json")
        rendering_doc = dict(doc)
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as jf:
                    per_msg = json.load(jf)
                # prefer fields from the per-message JSON (which usually contains the full body/html)
                rendering_doc.update(per_msg)
            except Exception:
                # if loading fails, fall back to docs.json entry
                pass

        # If still no useful body, try the out/by_year NDJSON index (normalize IDs & fallbacks)
        field, content = pick_text(rendering_doc)
        if not content or not str(content).strip():
            # try direct id lookups
            candidates = [mid, _norm_id(mid)]
            # also try other id variants from the docs entry
            for k in ("_id", "message-id", "message_id", "msgid", "id"):
                v = doc.get(k)
                if v:
                    candidates.append(_norm_id(v))
            # try subject+date hash key
            subj = doc.get("subject", "")
            date = doc.get("date") or doc.get("datetime") or ""
            if subj or date:
                candidates.append("hash:" + str(abs(hash((subj, date)))))
            # lookup in NDJSON index
            for cid in candidates:
                if cid in ndjson_index:
                    rendering_doc = ndjson_index[cid]
                    break

        # determine prev/next based on ordered_mids
        idx = mid_to_index.get(mid, None)
        prev_mid = ordered_mids[idx - 1] if (idx is not None and idx > 0) else None
        next_mid = ordered_mids[idx + 1] if (idx is not None and idx < len(ordered_mids) - 1) else None

        # attach thread prev/next into the rendering doc if available
        # prev_next_in_thread is built earlier: map mid -> (prev_mid_thread, next_mid_thread)
        pnt = prev_next_in_thread.get(mid)
        if pnt:
            # ensure rendering_doc contains the thread navigation keys
            rendering_doc["_prev_in_thread"] = pnt[0]
            rendering_doc["_next_in_thread"] = pnt[1]

        # render HTML
        html = render_message_html(rendering_doc, prev_mid, next_mid)

        # write to per-message files under site/msg/
        out_path = os.path.join(MSG_HTML_DIR, f"{mid}.html")
        try:
            # sanitize accidental diff markers that got embedded before tags
            html_out = re.sub(r'(?m)^[\+\-]+(?=<)', '', html)
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(html_out)
            written += 1
        except Exception as e:
            print("error writing", out_path, e)
            continue

    # write browse-by-year pages into site/browse/
    ensure_dir(BROWSE_DIR)
    years = {}
    for doc in docs:
        y = get_year(doc)
        years.setdefault(y, []).append(doc)

    def sort_key(d):
        # try to sort by date (string fallback)
        v = d.get("date") or d.get("datetime") or ""
        return v or ""

    for year, docs_in_year in years.items():
        lines = []
        # include nav placeholder (nav.html will be loaded client-side)
        lines.append(f"<!doctype html>\n<html><head><meta charset='utf-8'><title>Messages — {escape(year)}</title></head><body>")
        lines.append(NAV_INCLUDE_SNIPPET)
        lines.append(f"<main style='max-width:880px;margin:1rem auto;padding:0 1rem;'><h1>Messages — {escape(year)}</h1>")
        lines.append("<p><a href='index.html'>Back to browse index</a></p>")
        lines.append("<ul>")
        for d in sorted(docs_in_year, key=sort_key, reverse=True):
            mid = compute_mid(d)
            subj = escape(str(d.get("subject", "(no subject)")))
            sender = escape(str(d.get("from", d.get("author", "") ) ))
            date = escape(str(d.get("date", d.get("datetime", ""))))
            link = f"../msg/{urllib.parse.quote(mid)}.html"
            lines.append(f"<li><a href='{link}'>{subj}</a> — {sender} — {date}</li>")
        lines.append("</ul></main></body></html>")
        out_path = os.path.join(BROWSE_DIR, f"{year}.html")
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
        except Exception as e:
            print("error writing", out_path, e)

    # --- build authors grouping and write per-author pages ------------------
    authors = {}
    for d in docs:
        an = _author_name_from_doc(d) or "Unknown"
        authors.setdefault(an, []).append(d)

    authors_dir = os.path.join(BROWSE_DIR, "authors")
    ensure_dir(authors_dir)

    # sort authors by number of messages (desc), then by author name (asc)
    for author, msgs in sorted(authors.items(), key=lambda kv: (-len(kv[1]), kv[0].lower())):
        slug = _slugify(author)
        safe_dir = authors_dir  # one level only
        # sort messages by date desc same as years
        msgs_sorted = sorted(msgs, key=sort_key, reverse=True)
        lines = []
        lines.append("<!doctype html>\n<html><head><meta charset='utf-8'>")
        lines.append(f"<title>Messages by {escape(author)}</title></head><body>")
        lines.append(NAV_INCLUDE_SNIPPET)
        lines.append(f"<main style='max-width:880px;margin:1rem auto;padding:0 1rem;'><h1>Messages by {escape(author)}</h1>")
        lines.append("<p><a href='../index.html'>Back to browse index</a></p>")
        lines.append("<ul>")
        for d in msgs_sorted:
            mid = compute_mid(d)
            subj = escape(str(d.get("subject", "(no subject)")))
            date = escape(str(d.get("date", d.get("datetime", ""))))
            link = f"../../msg/{urllib.parse.quote(mid)}.html"
            lines.append(f"<li><a href='{link}'>{subj}</a> — {date}</li>")
        lines.append("</ul></main></body></html>")

        out_path = os.path.join(safe_dir, f"{slug}.html")
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
        except Exception as e:
            print("error writing author page", out_path, e)

    # write per-author pages (already done above)
    # now write authors index sorted by message count (desc), then name
    try:
        auth_idx_lines = []
        auth_idx_lines.append("<!doctype html>\n<html><head><meta charset='utf-8'><title>Browse authors</title></head><body>")
        auth_idx_lines.append(NAV_INCLUDE_SNIPPET)
        auth_idx_lines.append("<main style='max-width:880px;margin:1rem auto;padding:0 1rem;'><h1>Browse by author</h1><ul>")
        for author, msgs in sorted(authors.items(), key=lambda kv: (-len(kv[1]), kv[0].lower())):
            slug = _slugify(author)
            auth_idx_lines.append(f"<li><a href='{urllib.parse.quote(slug)}.html'>{escape(author)}</a> ({len(msgs)})</li>")
        auth_idx_lines.append("</ul></main></body></html>")
        with open(os.path.join(authors_dir, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(auth_idx_lines))
    except Exception as e:
        print("error writing authors index", e)

    # Insert Authors link into the main browse index (if you build idx_lines as before)
    # e.g. after idx_lines.append("<p>Years:</p><ul>") and before closing, add:
    # idx_lines.append("</ul>")
    # idx_lines.append("<p><a href='authors/index.html'>Browse by author</a></p>")

    # write main browse index
    idx_lines = []
    idx_lines.append("<!doctype html>\n<html><head><meta charset='utf-8'><title>Browse</title></head><body>")
    idx_lines.append(NAV_INCLUDE_SNIPPET)
    idx_lines.append("<main style='max-width:880px;margin:1rem auto;padding:0 1rem;'>")
    idx_lines.append("<h1>Browse messages</h1>")
    idx_lines.append("<p>Years:</p><ul>")
    for year in sorted(years.keys(), reverse=True):
        idx_lines.append(f"<li><a href='{escape(year)}.html'>{escape(year)}</a> ({len(years[year])})</li>")
    idx_lines.append("</ul>")
    idx_lines.append("<p><a href='../index.html'>Search</a></p>")
    idx_lines.append("<p><a href='authors/index.html'>Browse by author</a></p>")
    idx_lines.append("</main></body></html>")
    try:
        with open(os.path.join(BROWSE_DIR, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(idx_lines))
    except Exception as e:
        print("error writing browse index", e)

    print(f"Wrote {written} per-message HTML files to site/msg/ and {len(years)} browse year pages to site/browse/.")
    if missed_bodies:
        print(f"Warning: {missed_bodies} messages had missing bodies and were not indexed.")

if __name__ == "__main__":
    main()