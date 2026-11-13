"""Copy public road registers (lists of roads with road number, name, ends, length) that state departments publish as documents,
into the bucket. One queue item is one address.

Payload "kind": "page": a listing page. The page is kept (pages/<hash>.html.gz). Documents linked from it whose address matches
"docs" (a regex; documents may sit on another host, such as the S3WaaS file store cdnbbsr.s3waas.gov.in) are queued as "file"
items with the link text as their title. Pages on the same host whose address matches "follow" are queued as "page" items, up
to "depth" steps from the start.
Payload "kind": "file": one document. It is kept as docs/<host>/<path> with one record (address, title, source page, size, sha256,
content type). On a GitHub runner, the text of a PDF is also kept (pdftotext -layout, docs/.../<name>.txt), so that parsing reads
the bucket copy and this server does no PDF work.
No login, no form, no captcha. Record ids are the address's hash, so a rerun replaces, never doubles.
Local test: python docs.py --local <page url> <docs regex> (one page; files under /tmp/docs-test)."""
import gzip
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urljoin, urlsplit, unquote

import requests
import urllib3
from scrape_hub_client import HubClient, LocalHub, seed_queue, stop_flag, timed_get

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; s1d-labs public records crawl; +https://labs.s1d.me)"}
MAX_BYTES = 300 * 1024 * 1024
A = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
stop = stop_flag(install=False)


def key_of(url):
    return hashlib.sha1(url.encode()).hexdigest()[:20]


def text_of(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def row_title(page, pos):
    """The text of the table row (or list item) that holds the link at pos: the document's title on S3WaaS lists."""
    start = max(page.rfind("<tr", 0, pos), page.rfind("<li", 0, pos))
    if start < 0:
        return ""
    end = page.find("</tr>" if page[start:start + 3].lower() == "<tr" else "</li>", pos)
    return text_of(page[start:end if end > 0 else pos + 500])[:400]


def links(page, base):
    out, seen = [], set()
    for m in A.finditer(page):
        h = HREF.search(m.group(1))
        if not h:
            continue
        u = urljoin(base, html.unescape(h.group(1).strip())).split("#")[0]
        if not u.startswith(("http://", "https://")) or u in seen:
            continue
        seen.add(u)
        out.append((u, text_of(m.group(2))[:300], row_title(page, m.start())))
    return out


def safe_path(url):
    u = urlsplit(url)
    p = re.sub(r"[^A-Za-z0-9._/-]+", "_", unquote(u.path)).strip("/")[-180:] or "index"
    if u.query:     # index.php?title=A and ?title=B are different files
        p += "_" + re.sub(r"[^A-Za-z0-9._-]+", "_", unquote(u.query))[:80] + "_" + hashlib.sha1(u.query.encode()).hexdigest()[:8]
    return f"docs/{u.hostname}/{p}"


def get(hub, s, url, gap):
    for attempt in range(3):
        r = timed_get(hub, s, url, timeout=(20, 300), raise_errors=attempt == 2)
        time.sleep(gap)
        if r is not None and r.status_code == 200:
            return r
        if r is not None and r.status_code in (403, 429):
            if hasattr(hub, "block"):
                hub.block()
            raise RuntimeError(f"HTTP {r.status_code}")
        if r is not None and r.status_code in (404, 410):
            return r
        time.sleep(10 * (attempt + 1))
    raise RuntimeError("no answer")


def pdf_text(body):
    if not shutil.which("pdftotext"):
        return None
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "a.pdf")
        open(src, "wb").write(body)
        try:
            subprocess.run(["pdftotext", "-layout", src, os.path.join(d, "a.txt")], timeout=600, check=True, capture_output=True)
            return open(os.path.join(d, "a.txt"), "rb").read()
        except Exception:
            return None


def work(hub, s, item, project, gap, on_runner):
    p = item["payload"]
    url = p["url"]
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    r = get(hub, s, url, gap)
    if r.status_code != 200:
        hub.record(key_of(url), {"type": p["kind"], "url": url, "status": r.status_code, "from": p.get("from", ""), "fetched_at": now})
        hub.complete([item["key"]], "done", fetched=0)
        return
    body = r.content
    if len(body) > MAX_BYTES:
        raise RuntimeError("too big")
    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
    sha = hashlib.sha256(body).hexdigest()
    if p["kind"] == "page":
        page = body.decode(r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else "utf-8", "replace")
        path = f"pages/{key_of(url)}.html.gz"
        hub.upload_many([(path, gzip.compress(body, 6), "application/gzip")])
        found = links(page, r.url)
        docs_re = re.compile(p.get("docs") or r"\.(pdf|xlsx?|csv|zip|docx?)$", re.I)
        follow_re = re.compile(p["follow"], re.I) if p.get("follow") else None
        host = urlsplit(r.url).hostname
        new, ndocs, npages = [], 0, 0
        for u, label, row in found:
            if docs_re.search(u):
                new.append({"key": "f-" + key_of(u), "payload": {"kind": "file", "url": u, "title": row or label, "label": label,
                                                                   "from": url, "set": p.get("set", "")}})
                ndocs += 1
            elif follow_re and p.get("depth", 0) > 0 and urlsplit(u).hostname == host and follow_re.search(u):
                new.append({"key": "p-" + key_of(u), "payload": {**p, "url": u, "depth": p["depth"] - 1, "from": url}})
                npages += 1
        if new:
            seed_queue(project, new)
        hub.record(key_of(url), {"type": "page", "url": url, "final_url": r.url, "file": path, "sha256": sha, "docs": ndocs,
                                 "pages": npages, "from": p.get("from", ""), "set": p.get("set", ""), "fetched_at": now})
        hub.complete([item["key"]], "done", fetched=1)
        return
    path = safe_path(r.url if urlsplit(r.url).hostname else url)
    files = [(path, body, ctype or "application/octet-stream")]
    rec = {"type": "file", "url": url, "final_url": r.url, "title": p.get("title", ""), "label": p.get("label", ""), "from": p.get("from", ""),
           "set": p.get("set", ""), "file": path, "bytes": len(body), "sha256": sha, "content_type": ctype,
           "last_modified": r.headers.get("last-modified", ""), "fetched_at": now}
    if on_runner and (body[:5] == b"%PDF-"):
        t = pdf_text(body)
        if t is not None:
            files.append((path + ".txt", t, "text/plain; charset=utf-8"))
            rec.update(text_file=path + ".txt", text_chars=len(t))
    hub.upload_many(files)
    hub.record(key_of(url), rec)
    hub.complete([item["key"]], "done", fetched=1)


def main():
    project = os.environ["SCRAPE_POOL_PROJECT"]
    deadline = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 300
    hub = HubClient(project, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", 0)), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", 1)))
    stop_flag()
    gap = max(1.0, hub.settings.get("delay_ms", 2000) / 1000)
    on_runner = os.environ.get("GITHUB_ACTIONS") == "true"
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        while time.time() < deadline and not stop.is_set():
            if hub.settings.get("paused"):
                time.sleep(30)
                continue
            items = hub.claim(1, steal=True, retry_failed=True)
            if not items:
                break
            item = items[0]
            s.verify = item["payload"].get("verify", True)
            try:
                work(hub, s, item, project, gap, on_runner)
            except Exception as e:      # one bad item must not stop the run
                hub.failure("bad-item", item["key"], f"{type(e).__name__}: {e}"[:200])
                hub.complete([item["key"]], "failed", error=type(e).__name__)
        hub.close("finished" if not stop.is_set() else "failed", "" if not stop.is_set() else "stopped by signal")
    except Exception as e:
        hub.close("failed", str(e)[:200])
        raise


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[1] == "--local":
        hub = LocalHub(save_dir="/tmp/docs-test")
        s = requests.Session()
        s.headers.update(HEADERS)
        r = s.get(sys.argv[2], timeout=60)
        rx = re.compile(sys.argv[3], re.I)
        for u, label, row in links(r.text, r.url):
            if rx.search(u):
                print(u, "|", (row or label)[:120])
        sys.exit(0)
    sys.exit(main())
