# road-maps

A family of the s1d-labs scrape pool: public road maps as line geometry, for placing road tenders on the road they name
(road.s1d.me).

| Project | Source | What |
|---|---|---|
| road-maps-drrp | Esri India Living Atlas, `PMGSY/IN_DRRP_Road_2021` | every rural road of PMGSY's District Rural Road Plan (1.12 million lines, 2021) |
| road-maps-pmgsy3 | Esri India Living Atlas, `PMGSY/IN_PMSGY_Proposals_2021` | PMGSY-III proposal alignments 2019-2021 (16,240 lines) |

The government viewer (geosadak-pmgsy.nic.in) does not resolve (2026-11-11), so the Esri India mirror is the source. It is a 2021
copy, not the live register.

Task `arcgis` (arcgis.py) copies any public ArcGIS layer: item `count` queues pages of 2000 features by object id; each page is checked
against the layer's own count and stored as `<layer>/<first id>.geojson.gz` in the bucket. Local test:
`python arcgis.py --local <layer url> 1`.
