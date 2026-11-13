"""Reachability check from a GitHub runner (outside India): one GET per queue item, the answer kept in the bucket.
Used once (2026-11-13) for Kerala GIS hosts that do not answer dev-vps-3. Metadata pages only (service directories, capabilities);
no login, no form, no token. Payload: {"url": ...}. Record: HTTP status, bytes, content type, error, final URL."""
import gzip
import os
import re
import time

import requests
from scrape_hub_client import HubClient, stop_flag, timed_get

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; s1d-labs public records check; +https://labs.s1d.me)"}
stop = stop_flag(install=False)


def main():
    hub = HubClient(os.environ["SCRAPE_POOL_PROJECT"], job_index=int(os.environ.get("SCRAPE_JOB_INDEX", 0)),
                    total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", 1)))
    stop_flag()
    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = False
    requests.packages.urllib3.disable_warnings()
    while not stop.is_set():
        items = hub.claim(1, steal=True)
        if not items:
            break
        item = items[0]
        url = item["payload"]["url"]
        rec = {"url": url, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "runner": "github"}
        try:
            r = timed_get(hub, s, url, timeout=(20, 60), raise_errors=True)
            rec.update(status=r.status_code, bytes=len(r.content), type=r.headers.get("content-type", ""), final_url=r.url)
            if r.content:
                path = "kerala-probe/" + re.sub(r"[^A-Za-z0-9._-]+", "_", item["key"])[:120] + ".gz"
                hub.upload_many([(path, gzip.compress(r.content[:20_000_000], 6), "application/gzip")])
                rec["file"] = path
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"[:300]
        hub.record(item["key"], rec)
        hub.complete([item["key"]], "done", fetched=1)
        time.sleep(2)
    hub.close("finished", "")


if __name__ == "__main__":
    main()
