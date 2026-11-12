"""Copy a public ArcGIS map layer (MapServer or FeatureServer) into the bucket, one page of features per queue item, with geometry
in longitude/latitude (EPSG:4326). No login, no token: only layers that answer anonymous queries.

Queue items: "count" (asks the layer how many features it has and the object id range, then queues the pages) and "p-<first id>"
(object ids first .. first+size-1). A page file is <layer>/<first id>.geojson.gz; a record per page, id "<layer>-<first id>", with
the number of features and the file. A page is checked: the features that come back must equal the layer's count for that id range.
Local test: python arcgis.py --local <layer url> <first id> (one page, files saved under /tmp/arcgis-test)."""
import gzip
import json
import os
import sys
import time

import requests
from scrape_hub_client import HubClient, LocalHub, seed_queue, stop_flag, timed_get

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; s1d-labs public records crawl; +https://labs.s1d.me)"}
stop = stop_flag(install=False)     # set on SIGINT / SIGTERM once main() installs the handlers


class Layer:
    def __init__(self, url, hub=None, gap=1.0):
        self.url, self.hub, self.gap, self.last = url.rstrip("/"), hub, gap, 0.0
        self.s = requests.Session()
        self.s.headers.update(HEADERS)

    def query(self, **params):
        wait = self.last + self.gap - time.time()
        if wait > 0:
            time.sleep(wait)
        for attempt in range(4):
            # request metrics for the hub (none when hub is None); the last attempt raises a connection error
            r = timed_get(self.hub, self.s, self.url + "/query", params=params, timeout=(20, 300), raise_errors=attempt == 3)
            self.last = time.time()
            if r is None:
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code == 200:
                d = r.json()
                if "error" not in d:            # ArcGIS reports errors in a 200 answer
                    return d, r.content
            if attempt == 3:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            time.sleep(10 * (attempt + 1))

    def stats(self, oid):
        st = [{"statisticType": k, "onStatisticField": oid, "outStatisticFieldName": k} for k in ("min", "max", "count")]
        d, _ = self.query(where="1=1", outStatistics=json.dumps(st), f="json")
        a = d["features"][0]["attributes"]
        return {k.lower(): v for k, v in a.items()}

    def count(self, oid, a, b):
        d, _ = self.query(where=f"{oid}>={a} and {oid}<={b}", returnCountOnly="true", f="json")
        return d["count"]

    def page(self, oid, a, b):
        return self.query(where=f"{oid}>={a} and {oid}<={b}", outFields="*", outSR=4326, returnGeometry="true", f="geojson")


def run_count(hub, L, item, seed, project, p):
    s = L.stats(p["oid"])
    size = p["size"]
    items = [{"key": f"p-{a}", "payload": {**p, "a": a, "b": a + size - 1}} for a in range(int(s["min"]), int(s["max"]) + 1, size)]
    seed(project, items)
    hub.record(f"{p['name']}-layer", {"layer": p["url"], "name": p["name"], "features": s["count"], "min_id": s["min"], "max_id": s["max"],
                                     "pages": len(items), "counted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    hub.complete([item["key"]], "done", fetched=len(items))


def run_page(hub, L, item, p):
    a, b, oid = p["a"], p["b"], p["oid"]
    want = L.count(oid, a, b)
    d, raw = L.page(oid, a, b)
    got = len(d.get("features") or [])
    if got != want or d.get("exceededTransferLimit"):
        hub.failure("short-page", item["key"], f"wanted {want}, got {got}")
        hub.complete([item["key"]], "failed", error="short page")
        return
    path = f"{p['name']}/{a:09d}.geojson.gz"
    hub.upload_many([(path, gzip.compress(raw, 6), "application/gzip")])
    types = sorted({(f.get("geometry") or {}).get("type") or "none" for f in d["features"]})
    hub.record(f"{p['name']}-{a:09d}", {"layer": p["url"], "name": p["name"], "first_id": a, "last_id": b, "features": got, "geometry": types,
                                        "file": path, "bytes": len(raw), "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    hub.complete([item["key"]], "done", fetched=got)


def main():
    project = os.environ["SCRAPE_POOL_PROJECT"]
    deadline = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 300
    hub = HubClient(project, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", 0)), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", 1)))
    stop_flag()
    gap = max(0.5, hub.settings.get("delay_ms", 1000) / 1000)
    layers = {}
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
            L = layers.setdefault(p["url"], Layer(p["url"], hub, gap))
            try:
                if item["key"] == "count":
                    run_count(hub, L, item, seed_queue, project, p)
                else:
                    run_page(hub, L, item, p)
            except Exception as e:      # one bad page must not stop the run
                hub.failure("bad-item", item["key"], f"{type(e).__name__}: {e}"[:200])
                hub.complete([item["key"]], "failed", error=type(e).__name__)
        hub.close("finished" if not stop.is_set() else "failed", "" if not stop.is_set() else "stopped by signal")
    except Exception as e:
        hub.close("failed", str(e)[:200])
        raise


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[1] == "--local":
        url, a = sys.argv[2], int(sys.argv[3])
        p = {"url": url, "name": "local", "oid": "objectid", "size": 2000}
        hub = LocalHub(save_dir="/tmp/arcgis-test")
        L = Layer(url)
        run_count(hub, L, {"key": "count"}, lambda project, items: print("seeded", len(items), items[0]["key"], items[-1]["key"]), "local", p)
        run_page(hub, L, {"key": f"p-{a}"}, {**p, "a": a, "b": a + 1999})
        sys.exit(0)
    sys.exit(main())
