"""What this family scrapes: public road maps as line geometry, for placing road tenders on the road they name.

- road-maps-drrp: the District Rural Road Plan of PMGSY (every rural road in 29 states: road code, name, category, owner, district
  and block, 2021). The government viewer (geosadak-pmgsy.nic.in) is offline; Esri India's Living Atlas serves the same layer as a
  public ArcGIS map service with no login.
- road-maps-pmgsy3: PMGSY-III proposal alignments (2019-2021): work name, core network code, proposed length, year and batch.

One queue item "count" asks the layer for its size and queues the pages; a page is 2000 features by object id. Files are gzipped
GeoJSON in the bucket. The service is not geo-blocked, so GitHub runners do the work with no proxy."""
import json
from pathlib import Path

FAMILY = json.loads((Path(__file__).parent / "scrape.json").read_text())["family"]
ESRI_IN = "https://livingatlas.esri.in/server1/rest/services/PMGSY"
LAYERS = [
    ("drrp", f"{ESRI_IN}/IN_DRRP_Road_2021/MapServer/0", "PMGSY District Rural Road Plan: every rural road as a line (Esri India mirror, 2021)"),
    ("pmgsy3", f"{ESRI_IN}/IN_PMSGY_Proposals_2021/MapServer/0", "PMGSY-III proposal alignments 2019-2021 as lines (Esri India mirror)"),
]

PROJECTS = [
    {
        "name": f"{FAMILY}-{name}",
        "title": title,
        "task": "arcgis",
        "target": "livingatlas.esri.in",
        "env": {},
        "probe": None,
        "unit_label": "page of 2000 features", "record_label": "page",
        "items": [{"key": "count", "payload": {"url": url, "name": name, "oid": "objectid", "size": 2000}}],
        "workers": 3,
        "delay_ms": 1000,
    }
    for name, url, title in LAYERS
]

PROBES = [{"name": f"{FAMILY}:livingatlas.esri.in", "url": f"{ESRI_IN}/IN_DRRP_Road_2021/MapServer/0?f=json", "expect": "District Rural Road"}]
