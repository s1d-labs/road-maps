"""Copy large public data files (GitHub release assets and similar fixed downloads) into the bucket, byte for byte.

Queue item payload: {"url": ..., "name": "<folder>", "file": "<file name>", "source": "<where the data comes from>"}.
The file is read as a stream and stored in parts of at most PART_MB (default 200 MB): <name>/<file>.part000, .part001, ...
(one part only: <name>/<file>). Each part is checked by the storage checksum (upload_many). One record per file, id "<name>/<file>":
url, final address after redirects, bytes, sha256 of the whole file, the parts with their bytes and sha256, source, fetched_at.
Join the parts in order (cat <file>.part* > <file>) to get the original file; its sha256 must equal the record's sha256.
Local test: python release.py --local <url>  (reads the file, prints its size and sha256, stores nothing)."""
import hashlib
import os
import sys
import time

import requests
from scrape_hub_client import HubClient, stop_flag

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; s1d-labs public records crawl; +https://labs.s1d.me)"}
PART = int(os.environ.get("PART_MB", "200")) * 1024 * 1024
stop = stop_flag(install=False)


def parts(r):
    """Yield the body in parts of PART bytes."""
    buf = bytearray()
    for chunk in r.iter_content(1024 * 1024):
        buf += chunk
        while len(buf) >= PART:
            yield bytes(buf[:PART])
            del buf[:PART]
    if buf:
        yield bytes(buf)


def copy(hub, s, p):
    t = time.time()
    r = s.get(p["url"], stream=True, timeout=(30, 600), allow_redirects=True)
    if hub:
        hub.metric("n_http")
    if r.status_code != 200:
        if hub:
            hub.metric(f"http_{r.status_code}")
            if r.status_code in (403, 429, 503):
                hub.block()
        raise RuntimeError(f"HTTP {r.status_code}")
    total, whole, stored = 0, hashlib.sha256(), []
    want = int(r.headers.get("Content-Length") or 0)
    pending = None          # hold one part back so a file of one part keeps its own name
    for i, data in enumerate(parts(r)):
        total += len(data)
        whole.update(data)
        if pending is not None:
            stored.append(put(hub, p, pending[0], pending[1], True))
        pending = (i, data)
    if pending is not None:
        stored.append(put(hub, p, pending[0], pending[1], len(stored) > 0 or pending[0] > 0))
    if hub:
        hub.metric("t_http_s", time.time() - t)
    if want and total != want:
        raise RuntimeError(f"short read: {total} of {want} bytes")
    return {"url": p["url"], "final_url": r.url.split("?")[0], "bytes": total, "sha256": whole.hexdigest(), "parts": stored,
            "source": p.get("source", ""), "file": p["file"], "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def put(hub, p, i, data, split):
    path = f"{p['name']}/{p['file']}" + (f".part{i:03d}" if split else "")
    if hub is None:
        return {"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    out = hub.upload_many([(path, data, "application/octet-stream")])[0]
    return {"path": path, "key": out["key"], "bytes": out["bytes"], "sha256": out["sha256"]}


def main():
    project = os.environ["SCRAPE_POOL_PROJECT"]
    deadline = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 300
    hub = HubClient(project, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", 0)), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", 1)))
    stop_flag()
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
            p = item["payload"]
            try:
                rec = copy(hub, s, p)
                hub.record(f"{p['name']}/{p['file']}", rec)
                hub.complete([item["key"]], "done", fetched=1)
            except Exception as e:
                hub.error()
                hub.failure("bad-item", item["key"], f"{type(e).__name__}: {e}"[:200])
                hub.complete([item["key"]], "failed", error=type(e).__name__)
            time.sleep(max(1.0, hub.settings.get("delay_ms", 2000) / 1000))
        hub.close("finished" if not stop.is_set() else "failed", "" if not stop.is_set() else "stopped by signal")
    except Exception as e:
        hub.close("failed", str(e)[:200])
        raise


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--local":
        u = sys.argv[2]
        s = requests.Session()
        s.headers.update(HEADERS)
        rec = copy(None, s, {"url": u, "name": "local", "file": u.rsplit("/", 1)[-1]})
        print(rec["bytes"], rec["sha256"], len(rec["parts"]), "parts")
        sys.exit(0)
    sys.exit(main())
