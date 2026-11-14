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

More projects (2026-11-13/14; the full list with fields and counts is in family.py):

| Project | Source | What |
|---|---|---|
| road-maps-jh | Jharkhand JSAC `Transportation_Infra`, `PMGSY` | NH 42, SH 58, district roads 468, PMGSY roads 11,729 with core network numbers |
| road-maps-mp-rams | MPRDC RAMS `BRIDGE/1` road join, `NH` | 11,718 PWD/MPRDC road segments (676 with geometry on the server) with road number, ends and chainage; NH 96 |
| road-maps-pmgsy-hab | Esri India Living Atlas, `PMGSY/IN_Habitation_2021` | 1,084,173 PMGSY habitation points (name, population, district, block) |
| road-maps-compiled | github.com/ramSeraph/indian_transport releases (CC0 compilation) | Survey of India roads, NIC Bharatmaps street roads, PMGSY open data 2022 (proposals I/II/III/RCPLWEA, core network candidates), GatiShakti MoRTH NH, AMRUT and NUIS urban roads |

Task `release` (release.py) stores a large public file byte for byte in parts of 200 MB (`<file>.part000` ...); the record holds the
sha256 of the whole file. Task `arcgis` splits a page whose query the server fails because of one bad feature, and keeps a single
bad feature's attributes without geometry (`no_geometry`).
