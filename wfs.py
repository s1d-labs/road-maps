"""Copy a public WFS layer (GeoServer) into the bucket, one page of features per queue item, as GeoJSON in longitude/latitude
(EPSG:4326). No login, no token: only layers that answer anonymous GetFeature requests.

Queue items: "count-<layer>" (asks the server how many features the layer has with resultType=hits, stores the layer's
DescribeFeatureType answer, then queues the pages) and "<layer>-p-<start>" (features start .. start+size-1 in a fixed order:
payload "sort" names the field to sort by, for layers without a primary key). A page file is <layer>/<start>.geojson.gz; a record per
page, id "<layer>-<start>", with the number of features and the file. A page is checked: it must hold the number of features that
the count promised for that range.
Payload: {"url": WFS endpoint, "type": typeName, "name": layer name in the bucket, "size": page size, "sort": optional field,
"props": optional comma list of attributes (attribute-only copy for layers whose geometry the server cannot write)}.
Local test: python wfs.py --local <wfs url> <typeName> (one page, files saved under /tmp/wfs-test)."""
import gzip
import os
import re
import sys
import time

import requests
from scrape_hub_client import HubClient, LocalHub, seed_queue, stop_flag, timed_get

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; s1d-labs public records crawl; +https://labs.s1d.me)"}
stop = stop_flag(install=False)     # set on SIGINT / SIGTERM once main() installs the handlers


class Wfs:
    def __init__(self, url, hub=None, gap=1.0):
        self.url, self.hub, self.gap, self.last = url, hub, gap, 0.0
        self.s = requests.Session()
        self.s.headers.update(HEADERS)

    def get(self, **params):
        base = {"service": "WFS", "version": "2.0.0"}
        for attempt in range(4):
            wait = self.last + self.gap - time.time()
            if wait > 0:
                time.sleep(wait)
            r = timed_get(self.hub, self.s, self.url, params={**base, **params}, timeout=(20, 300), raise_errors=attempt == 3)
            self.last = time.time()
            if r is not None and r.status_code == 200 and b"ExceptionReport" not in r.content[:2000]:
                return r
            if attempt == 3:
                raise RuntimeError(f"HTTP {getattr(r, 'status_code', '?')}: {getattr(r, 'text', '')[:200]}")
            time.sleep(10 * (attempt + 1))

    def hits(self, type_name):
        r = self.get(request="GetFeature", typeNames=type_name, resultType="hits")
        m = re.search(rb'numberMatched="(\d+)"', r.content) or re.search(rb'numberOfFeatures="(\d+)"', r.content)
        if not m:
            raise RuntimeError("no feature count in the hits answer")
        return int(m.group(1))

    def describe(self, type_name):
        return self.get(request="DescribeFeatureType", typeNames=type_name).content

    def page(self, type_name, start, size, sort=None, props=None):
        params = {"request": "GetFeature", "typeNames": type_name, "outputFormat": "application/json", "srsName": "EPSG:4326",
                  "count": size, "startIndex": start}
        if sort:
            params["sortBy"] = sort
        if props:       # attribute list: for layers whose stored geometry makes the server fail (NHAI: java.io.IOException)
            params["propertyName"] = props
        r = self.get(**params)
        return r.json(), r.content


def run_count(hub, W, item, seed, project, p):
    n = W.hits(p["type"])
    hub.upload_many([(f"{p['name']}/describe.xml.gz", gzip.compress(W.describe(p["type"]), 6), "application/gzip")])
    size = p["size"]
    items = [{"key": f"{p['name']}-p-{a}", "payload": {**p, "start": a, "want": min(size, n - a)}} for a in range(0, n, size)]
    seed(project, items)
    hub.record(f"{p['name']}-layer", {"layer": p["url"], "type": p["type"], "name": p["name"], "features": n, "pages": len(items),
                                     "page_size": size, "counted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    hub.complete([item["key"]], "done", fetched=len(items))


def run_page(hub, W, item, p):
    a = p["start"]
    d, raw = W.page(p["type"], a, p["size"], p.get("sort"), p.get("props"))
    got = len(d.get("features") or [])
    if got != p["want"]:
        hub.failure("short-page", item["key"], f"wanted {p['want']}, got {got}")
        hub.complete([item["key"]], "failed", error="short page")
        return
    path = f"{p['name']}/{a:09d}.geojson.gz"
    hub.upload_many([(path, gzip.compress(raw, 6), "application/gzip")])
    types = sorted({(f.get("geometry") or {}).get("type") or "none" for f in d["features"]})
    hub.record(f"{p['name']}-{a:09d}", {"layer": p["url"], "type": p["type"], "name": p["name"], "start": a, "features": got,
                                        "geometry": types, "file": path, "bytes": len(raw),
                                        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    hub.complete([item["key"]], "done", fetched=got)


def main():
    project = os.environ["SCRAPE_POOL_PROJECT"]
    deadline = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 300
    hub = HubClient(project, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", 0)), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", 1)))
    stop_flag()
    gap = max(0.5, hub.settings.get("delay_ms", 1000) / 1000)
    servers = {}
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
            W = servers.setdefault(p["url"], Wfs(p["url"], hub, gap))
            try:
                if item["key"].startswith("count-"):
                    run_count(hub, W, item, seed_queue, project, p)
                else:
                    run_page(hub, W, item, p)
            except Exception as e:      # one bad page must not stop the run
                hub.failure("bad-item", item["key"], f"{type(e).__name__}: {e}"[:200])
                hub.complete([item["key"]], "failed", error=type(e).__name__)
        hub.close("finished" if not stop.is_set() else "failed", "" if not stop.is_set() else "stopped by signal")
    except Exception as e:
        hub.close("failed", str(e)[:200])
        raise


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[1] == "--local":
        url, type_name = sys.argv[2], sys.argv[3]
        p = {"url": url, "type": type_name, "name": "local", "size": int(os.environ.get("SIZE", "500")), "sort": os.environ.get("SORT")}
        seen = {}
        hub = LocalHub(save_dir="/tmp/wfs-test")
        W = Wfs(url)
        run_count(hub, W, {"key": "count-local"}, lambda project, items: seen.update(items=items), "local", p)
        print("seeded", len(seen["items"]), seen["items"][0]["key"], seen["items"][-1]["key"])
        run_page(hub, W, seen["items"][0], seen["items"][0]["payload"])
        sys.exit(0)
    sys.exit(main())
