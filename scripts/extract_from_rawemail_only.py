import sys, os, json, gzip, re, datetime
from warcio.archiveiterator import ArchiveIterator
from email import policy
from email.parser import BytesParser
from html import unescape

warc_path = sys.argv[1]
os.makedirs("out/by_year", exist_ok=True)

def to_iso_and_year(ts):
    for k in (ts,):
        try:
            v = int(k)
            dt = datetime.datetime.utcfromtimestamp(v)
            return dt.isoformat() + "Z", dt.year
        except Exception:
            pass
    return None, None

def strip_html(s: str) -> str:
    if not s: return ""
    s = unescape(s)
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\\1>", "", s)
    s = re.sub(r"(?i)<\\s*br\\s*/?\\s*>", "\n", s)
    s = re.sub(r"(?i)</\\s*p\\s*>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"[ \\t\\r\\f\\v]+", " ", s)
    s = re.sub(r"\n\\s*\n\\s*\n+", "\n\n", s)
    return s.strip()

def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)

def email_to_text(raw: str) -> str:
    # Parse MIME and prefer text/plain; fallback to stripped text/html; else raw
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw.encode("utf-8", "ignore"))
    except Exception:
        return raw.replace("\r\n", "\n")
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            if ctype == "text/plain":
                try:
                    parts.append(part.get_content())
                except Exception:
                    b = part.get_payload(decode=True) or b""
                    parts.append(b.decode("utf-8", "ignore"))
            elif ctype == "text/html":
                try:
                    html = part.get_content()
                except Exception:
                    b = part.get_payload(decode=True) or b""
                    html = b.decode("utf-8", "ignore")
                parts.append(strip_html(html))
    else:
        ctype = (msg.get_content_type() or "").lower()
        try:
            content = msg.get_content()
        except Exception:
            b = msg.get_payload(decode=True) or b""
            content = b.decode("utf-8", "ignore")
        if ctype == "text/plain":
            parts.append(content)
        elif ctype == "text/html":
            parts.append(strip_html(content))
        else:
            parts.append(content)
    text = "\n".join(p for p in parts if p)
    return text.strip() or raw.replace("\r\n","\n")

seen = set()
count = 0
per_year = {}

opener = gzip.open if warc_path.endswith((".gz",".gzip")) else open
with opener(warc_path, "rb") as f, open("out/messages.ndjson","w",encoding="utf-8") as out:
    for rec in ArchiveIterator(f):
        if rec.rec_headers.get_header("WARC-Type") != "resource":
            continue
        if "json" not in (rec.rec_headers.get_header("Content-Type") or "").lower():
            continue
        try:
            data = json.loads(rec.content_stream().read().decode("utf-8","ignore"))
        except Exception:
            continue

        for d in walk(data):
            if not isinstance(d, dict): 
                continue
            mid = d.get("msgId") or d.get("messageId") or d.get("id")
            raw = d.get("rawEmail")
            if mid is None or not raw:
                continue

            mid = str(mid)
            if mid in seen: 
                continue
            seen.add(mid)

            # Build fields
            subject = (d.get("subject") or "").strip()
            author  = (d.get("authorName") or d.get("author") or d.get("yahooAlias") or d.get("from") or "").strip()
            # timestamps: prefer postDate (seen in your sample), else lastPosted/date
            ts_iso, year = to_iso_and_year(d.get("postDate") or d.get("lastPosted") or d.get("date"))
            thread = d.get("topicFirstRecord") or d.get("topicId") or mid

            full_text = email_to_text(raw)
            index_text = full_text[:1000]  # plain text already

            doc = {
                "id": mid,
                "thread_id": str(thread),
                "subject": subject,
                "author": author,
                "timestamp": ts_iso,
                "year": year,
                "index_text": index_text,
                "full_text": full_text,
            }
            line = json.dumps(doc, ensure_ascii=False)
            out.write(line + "\n")
            if year is not None:
                per_year.setdefault(year, []).append(line)
            count += 1

for y, lines in per_year.items():
    with open(f"out/by_year/{y}.ndjson","w",encoding="utf-8") as fy:
        fy.write("\n".join(lines) + "\n")

print(f"Wrote out/messages.ndjson with {count} full-body messages (rawEmail+msgId).")
