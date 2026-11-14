"""Copy a public ArcGIS map layer (MapServer or FeatureServer) into the bucket, one page of features per queue item, with geometry
in longitude/latitude (EPSG:4326). No login, no token: only layers that answer anonymous queries.

Queue items: "count" (asks the layer how many features it has and the object id range, then queues the pages) and "p-<first id>"
(object ids first .. first+size-1). Payload "fmt": "json" stores Esri JSON (<first id>.json.gz) for servers whose GeoJSON output
fails. A project with several layers uses "count-<layer>" and "<layer>-p-<first id>" (keys are unique
per project). A page file is <layer>/<first id>.geojson.gz; a record per page, id "<layer>-<first id>", with
the number of features and the file. A page is checked: the features that come back must equal the layer's count for that id range.
The count item also stores the layer description (<layer>/layer.json.gz: fields, copyright text) and pages by the real object ids
(the object-id field and the page size come from the layer unless the payload sets them).
Local test: python arcgis.py --local <layer url> <first id> (one page, files saved under /tmp/arcgis-test)."""
import gzip
import json
import os
import sys
import time

import requests
import urllib3
from scrape_hub_client import HubClient, LocalHub, seed_queue, stop_flag, timed_get

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; s1d-labs public records crawl; +https://labs.s1d.me)"}
stop = stop_flag(install=False)     # set on SIGINT / SIGTERM once main() installs the handlers


class Layer:
    def __init__(self, url, hub=None, gap=1.0, verify=True):
        self.url, self.hub, self.gap, self.last = url.rstrip("/"), hub, gap, 0.0
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.s.verify = verify      # False only for servers with a broken certificate (owner OK 2026-11-11; records say tls_unverified)

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

    def meta(self):
        """The layer's own description (fields, geometry type, object-id field, page limit, copyright text)."""
        wait = self.last + self.gap - time.time()
        if wait > 0:
            time.sleep(wait)
        r = timed_get(self.hub, self.s, self.url, params={"f": "json"}, timeout=(20, 120), raise_errors=True)
        self.last = time.time()
        d = r.json() if r is not None and r.status_code == 200 else {}
        return ({} if "error" in d else d), (r.content if r is not None else b"")

    def stats(self, oid):
        st = [{"statisticType": k, "onStatisticField": oid, "outStatisticFieldName": k} for k in ("min", "max", "count")]
        d, _ = self.query(where="1=1", outStatistics=json.dumps(st), f="json")
        a = d["features"][0]["attributes"]
        return {k.lower(): v for k, v in a.items()}

    def ids(self):
        """All object ids (sorted), for layers whose ids are sparse or whose server has no statistics."""
        d, _ = self.query(where="1=1", returnIdsOnly="true", f="json")
        return sorted(d.get("objectIds") or [])

    def count(self, oid, a, b):
        d, _ = self.query(where=f"{oid}>={a} and {oid}<={b}", returnCountOnly="true", f="json")
        return d["count"]

    def page(self, oid, a, b, fmt="geojson"):
        return self.query(where=f"{oid}>={a} and {oid}<={b}", outFields="*", outSR=4326, returnGeometry="true", f=fmt)


def run_count(hub, L, item, seed, project, p):
    meta, raw = L.meta()
    if meta:        # keep the layer description (fields, copyright text) next to the pages
        hub.upload_many([(f"{p['name']}/layer.json.gz", gzip.compress(raw, 6), "application/gzip")])
    oid = p.get("oid") or meta.get("objectIdField") or next((f["name"] for f in meta.get("fields") or []
                                                             if f.get("type") == "esriFieldTypeOID"), "objectid")
    size = min(p["size"], int(meta.get("maxRecordCount") or p["size"]))
    p = {**p, "oid": oid, "size": size}
    prefix = "" if item["key"] == "count" else f"{p['name']}-"
    try:
        ids = L.ids()
    except Exception:       # servers that refuse a full id list: fall back to the id range
        ids = None
    if ids:
        n, lo, hi = len(ids), ids[0], ids[-1]
        ranges = [(ids[i], ids[min(i + size, n) - 1]) for i in range(0, n, size)]
    else:
        s = L.stats(oid)
        n, lo, hi = s["count"], int(s["min"]), int(s["max"])
        ranges = [(a, a + size - 1) for a in range(lo, hi + 1, size)]
    items = [{"key": f"{prefix}p-{a}", "payload": {**p, "a": a, "b": b}} for a, b in ranges]
    seed(project, items)
    hub.record(f"{p['name']}-layer", {"layer": p["url"], "name": p["name"], "features": n, "min_id": lo, "max_id": hi, "oid": oid,
                                     "page_size": size, "pages": len(items), "geometry": meta.get("geometryType"),
                                     "fields": [f.get("name") for f in meta.get("fields") or []],
                                     "copyright": meta.get("copyrightText") or "", "max_record_count": meta.get("maxRecordCount"),
                                     "tls_unverified": p.get("verify") is False,
                                     "counted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    hub.complete([item["key"]], "done", fetched=len(items))


BAD_ROW = ("Failed to execute query", "java.io.IOException")


def run_page(hub, L, item, p, seed=None, project=None):
    a, b, oid = p["a"], p["b"], p["oid"]
    want = L.count(oid, a, b)
    fmt = p.get("fmt", "geojson")        # "json" (Esri JSON) for servers whose GeoJSON output fails (APSAC, ArcGIS 10.6)
    try:
        d, raw = L.page(oid, a, b, fmt)
    except RuntimeError as e:
        # Some servers fail a whole page for one feature whose stored geometry they cannot write (MP RAMS). Split the id range in
        # two new queue items; a single id that still fails is stored with its attributes only ("no_geometry": true).
        if not any(s in str(e) for s in BAD_ROW) or seed is None:
            raise
        if b > a:
            mid = (a + b) // 2
            seed(project, [{"key": f"{item['key']}/{x}-{y}", "payload": {**p, "a": x, "b": y}} for x, y in ((a, mid), (mid + 1, b))])
            hub.record(f"{p['name']}-split-{a:09d}-{b:09d}", {"layer": p["url"], "name": p["name"], "first_id": a, "last_id": b, "split": True,
                                                              "error": str(e)[:200]})
            hub.complete([item["key"]], "done", fetched=0)
            return
        d, raw = L.query(where=f"{oid}>={a} and {oid}<={b}", outFields="*", returnGeometry="false", f=fmt)
        p = {**p, "no_geometry": True}
    got = len(d.get("features") or [])
    if got != want or d.get("exceededTransferLimit"):
        hub.failure("short-page", item["key"], f"wanted {want}, got {got}")
        hub.complete([item["key"]], "failed", error="short page")
        return
    path = f"{p['name']}/{a:09d}.{fmt}.gz"
    hub.upload_many([(path, gzip.compress(raw, 6), "application/gzip")])
    types = sorted({(f.get("geometry") or {}).get("type") or "none" for f in d["features"]}) if fmt == "geojson" else [d.get("geometryType")]
    hub.record(f"{p['name']}-{a:09d}", {"layer": p["url"], "name": p["name"], "first_id": a, "last_id": b, "features": got, "geometry": types,
                                        "file": path, "bytes": len(raw), "tls_unverified": p.get("verify") is False, "no_geometry": p.get("no_geometry", False), "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
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
            L = layers.setdefault(p["url"], Layer(p["url"], hub, gap, p.get("verify", True)))
            try:
                if item["key"] == "count" or item["key"].startswith("count-"):
                    run_count(hub, L, item, seed_queue, project, p)
                else:
                    run_page(hub, L, item, p, seed_queue, project)
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
        p = {"url": url, "name": "local", "size": int(os.environ.get("SIZE", "2000")), "fmt": os.environ.get("FMT", "geojson")}
        seen = {}
        hub = LocalHub(save_dir="/tmp/arcgis-test")
        L = Layer(url)
        run_count(hub, L, {"key": "count"}, lambda project, items: seen.update(items=items), "local", p)
        items = seen["items"]
        print("seeded", len(items), items[0]["key"], items[-1]["key"])
        it = next((i for i in items if i["payload"]["a"] >= a), items[0])
        run_page(hub, L, it, it["payload"])
        sys.exit(0)
    sys.exit(main())
