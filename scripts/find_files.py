import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
NDJSON_DIR = os.path.join(ROOT, "out", "by_year")
WARC_DIR = os.path.join(ROOT, "data")

URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
FILE_EXT_RE = re.compile(r"\.(?:zip|tar|tgz|gz|rar|7z|pdf|docx?|xlsx?|pptx?|jpg|jpeg|png|gif|mp3|wav|exe|bin)(?:[?#/]|$)", re.I)

def scan_ndjson():
    if not os.path.isdir(NDJSON_DIR):
        print(f"NDJSON dir not found: {NDJSON_DIR}", file=sys.stderr)
        return
    for fn in sorted(os.listdir(NDJSON_DIR)):
        if not fn.endswith(".ndjson"):
            continue
        path = os.path.join(NDJSON_DIR, fn)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                mid = obj.get("id") or obj.get("_id") or obj.get("message-id") or ""
                # explicit attachments lists
                for key in ("attachments", "files", "enclosures"):
                    if obj.get(key):
                        for a in (obj.get(key) or []):
                            out = {
                                "source": "ndjson",
                                "file": a if isinstance(a, str) else a.get("filename") or a.get("url") or a,
                                "message": mid,
                                "meta_key": key,
                                "raw": a,
                            }
                            print(json.dumps(out, ensure_ascii=False))
                # scan body/text/html for URLs that look like file links
                bodies = []
                for k in ("full_text","index_text","html","body","text","content","raw","message"):
                    v = obj.get(k)
                    if isinstance(v, str) and v.strip():
                        bodies.append(v)
                if bodies:
                    s = "\n".join(bodies)
                    for url in set(URL_RE.findall(s)):
                        if FILE_EXT_RE.search(url) or "/attachments/" in url or "groups.yahoo.com" in url:
                            print(json.dumps({
                                "source":"ndjson",
                                "message": mid,
                                "candidate_url": url
                            }, ensure_ascii=False))

def scan_warc():
    try:
        from warcio.archiveiterator import ArchiveIterator
    except Exception:
        print("warcio not installed; skipping WARC scan. Install with: pip3 install warcio", file=sys.stderr)
        return
    if not os.path.isdir(WARC_DIR):
        print(f"WARC dir not found: {WARC_DIR}", file=sys.stderr)
        return
    for fn in sorted(os.listdir(WARC_DIR)):
        if not (fn.endswith(".warc") or fn.endswith(".warc.gz")):
            continue
        path = os.path.join(WARC_DIR, fn)
        try:
            with open(path, "rb") as fh:
                for rec in ArchiveIterator(fh):
                    # interested in HTTP responses with non-text content
                    if rec.rec_type != "response":
                        continue
                    http_headers = rec.http_headers
                    if not http_headers:
                        continue
                    ctype = http_headers.get_header("Content-Type") or ""
                    disp = http_headers.get_header("Content-Disposition") or ""
                    target = rec.rec_headers.get_header("WARC-Target-URI") or ""
                    if not ctype:
                        continue
                    if ctype.startswith("text/"):
                        continue
                    # anything non-text is a candidate (images, application/*, etc.)
                    print(json.dumps({
                        "source": "warc",
                        "warc_file": fn,
                        "uri": target,
                        "content_type": ctype,
                        "content_disposition": disp
                    }, ensure_ascii=False))
        except Exception as e:
            print("error reading", path, e, file=sys.stderr)

if __name__ == "__main__":
    scan_ndjson()
    scan_warc()