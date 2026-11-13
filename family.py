"""What this family scrapes: public road maps as line geometry, for placing road tenders on the road they name.

- road-maps-drrp: the District Rural Road Plan of PMGSY (every rural road in 29 states: road code, name, category, owner, district
  and block, 2021). The government viewer (geosadak-pmgsy.nic.in) is offline; Esri India's Living Atlas serves the same layer as a
  public ArcGIS map service with no login.
- road-maps-pmgsy3: PMGSY-III proposal alignments (2019-2021): work name, core network code, proposed length, year and batch.

One queue item "count" asks the layer for its size and queues the pages; a page is 2000 features by object id. Files are gzipped
GeoJSON in the bucket. The service is not geo-blocked, so GitHub runners do the work with no proxy.

Road networks with road codes and chainage (2026-11-13), so a tender for "km 12-18 of SH-45" can be cut out of the right road. The
layer list with fields, counts and licences: road-site/data/road_networks.md in the investigations repo.
- road-maps-tn: Tamil Nadu TNGIS WFS (NH, SH, MDR, ODR, rural and village roads with road numbers). GitHub runners, no proxy.
- road-maps-nhai: NHAI Datalake WFS (NH network, project alignments with old and new NH numbers and chainage, toll plazas).
- DIRECT projects (not in the pool, worked by a worker on dev-vps-3 in Mumbai with the server token): state GIS servers that may refuse
  foreign IPs. This keeps the hub's shared Mumbai proxies free. One project per server, one worker, a pause of 2 s or more:
  road-maps-ap-rb (APSAC: SH/MDR/ODR with start and end chainage, NH, SH and MDR works with km ranges), road-maps-bihar-rcd (Bihar
  RCD: NH with old and new NH number, SH, MDR, all RCD roads with section start/end and length), road-maps-ka (KSRSAC KGIS: NH, SH,
  MDR, AH, expressways with the road number; RDPR rural roads with the village/ODR/MDR road number and length), road-maps-bharatmaps
  (NIC Bharatmaps: national highways 2012 with old and new NH numbers, state highways), road-maps-wris (India-WRIS: NH, SH and
  expressways with type and number, old numbering), road-maps-tg-rb (Telangana TGRAC: road id with start and end chainage),
  road-maps-hr-pwd (Haryana PWD B&R), road-maps-mh-wardha (MRSAC Wardha works roads with ODR/VR numbers), road-maps-nhai.
Pages of dense state layers are small (APSAC: 100 features is about 29 MB of Esri JSON). "fmt": "json" stores Esri JSON, which
older ArcGIS servers answer more reliably than GeoJSON. "verify": false only where the server's certificate fails (marked
tls_unverified in the records)."""
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

# Esri India's "Road_Centerline_Bharatmala": 28,374 NH/SH lines with rdcodeprm/rdcodesec. The item terms limit offline export; the
# owner decided on 2026-11-13 that personal and team use is fine ("use everything").
LA = "https://livingatlas.esri.in/server/rest/services"
PROJECTS += [{
    "name": f"{FAMILY}-bharatmala", "title": "National and state highways with road codes (Esri India Bharatmala road network)",
    "task": "arcgis", "target": "livingatlas.esri.in", "env": {}, "probe": None,
    "unit_label": "page of 2000 features", "record_label": "page",
    "items": [{"key": "count", "payload": {"url": f"{LA}/Road_Network/Road_Centerline_Bharatmala/MapServer/0", "name": "bharatmala", "size": 2000}}],
    "workers": 1, "delay_ms": 1000,
}]

APSAC = "https://apsac.ap.gov.in/gisserver/rest/services"
AP_RB = f"{APSAC}/Gatishakti/Roads_Buildings/MapServer"
APRDC = f"{APSAC}/INFRASTRUCTURE/APRDC_layers/MapServer"
BIHAR = "https://gisserver.bihar.gov.in/arcgis/rest/services/RCD_DEPT"
KGIS = "https://kgis.ksrsac.in/kgismaps1/rest/services"
NIC = "https://mapservice.gov.in/mapserviceserv176/rest/services/NightLightData/NLT2012/MapServer"
WRIS = "https://arc.indiawris.gov.in/server/rest/services"

# name, title, target host, delay ms, page size, extra payload, layers [(layer name, url)]
DIRECT = [
    ("ap-rb", "Andhra Pradesh R&B roads with chainage and SH/MDR works (APSAC)", "apsac.ap.gov.in", 3000, 100, {"fmt": "json"}, [
        ("ap-nh", f"{AP_RB}/11"), ("ap-sh", f"{AP_RB}/12"), ("ap-mdr", f"{AP_RB}/13"), ("ap-odr", f"{AP_RB}/14"),
        ("ap-sh-pm-works", f"{APRDC}/0"), ("ap-mdr-sr-works", f"{APRDC}/1"), ("ap-sh-ur-works", f"{APRDC}/2"),
        ("ap-mdr-ur-works", f"{APRDC}/3"), ("ap-sh-aprdc", f"{APRDC}/5"), ("ap-mdr-aprdc", f"{APRDC}/6"), ("ap-odr-aprdc", f"{APRDC}/7")]),
    ("bihar-rcd", "Bihar RCD roads: NH (old and new number), SH, MDR, all RCD roads with section start and end", "gisserver.bihar.gov.in",
     2000, 200, {"fmt": "json"}, [
        ("br-nh", f"{BIHAR}/NHRoads/MapServer/0"), ("br-sh", f"{BIHAR}/SHRoads/MapServer/0"), ("br-mdr", f"{BIHAR}/MDR/MapServer/0"),
        ("br-rcd-roads", f"{BIHAR}/ROAD_BIHAR/MapServer/0"), ("br-expressway", f"{BIHAR}/ExpressWay/MapServer/0"),
        ("br-rcplwea", f"{BIHAR}/RCPLWEA/MapServer/0")]),
    ("ka", "Karnataka roads with road numbers: NH, SH, MDR, AH, expressways (PM Gati Shakti) and RDPR rural roads (KSRSAC KGIS)",
     "kgis.ksrsac.in", 2000, 1000, {"fmt": "json"}, [
        ("ka-ah", f"{KGIS}/PMGatiShakthi/PMGatiShakthi/MapServer/8"), ("ka-expressway", f"{KGIS}/PMGatiShakthi/PMGatiShakthi/MapServer/9"),
        ("ka-nh", f"{KGIS}/PMGatiShakthi/PMGatiShakthi/MapServer/10"), ("ka-sh", f"{KGIS}/PMGatiShakthi/PMGatiShakthi/MapServer/11"),
        ("ka-mdr", f"{KGIS}/PMGatiShakthi/PMGatiShakthi/MapServer/12"), ("ka-rdpr", f"{KGIS}/RDPR/KRRDA_Roads/MapServer/0")]),
    ("bharatmaps", "National highways 2012 with old and new NH numbers, and state highways (NIC Bharatmaps)", "mapservice.gov.in",
     2000, 500, {"fmt": "json", "verify": False}, [("nic-nh-2012", f"{NIC}/3"), ("nic-sh-2012", f"{NIC}/4")]),
    ("wris", "National and state highways, expressways and multilane roads with type and number (India-WRIS)", "arc.indiawris.gov.in",
     2000, 1000, {"fmt": "json"}, [
        ("wris-highways", f"{WRIS}/Common/Administrative_WRP/MapServer/8"),     # layers 7 and 8 are the same 8,076 lines
        ("wris-multilane", f"{WRIS}/DataDownload/Transportation_Layer/MapServer/2")]),
]
PROJECTS += [
    {
        "name": f"{FAMILY}-{name}", "title": title, "task": "arcgis", "target": target, "env": {}, "probe": None, "pool": False,
        "unit_label": f"page of up to {size} features", "record_label": "page",
        "items": [{"key": f"count-{layer}", "payload": {"url": url, "name": layer, "size": size, **extra}} for layer, url in layers],
        "workers": 1, "delay_ms": delay,
    }
    for name, title, target, delay, size, extra, layers in DIRECT
]

TGRAC = "https://tgrac.telangana.gov.in/arcgis/rest/services"
DIRECT_TG = ("tg-rb", "Telangana roads with road id and start and end chainage: R&B and PR network, NH, SH, MDR, ODR, lane details (TGRAC)",
             "tgrac.telangana.gov.in", 2000, 1000, {"fmt": "json"}, [
                 ("tg-road-from-to", f"{TGRAC}/RnB_Folder/RnB_Query/MapServer/0"), ("tg-road-network", f"{TGRAC}/RnB_Folder/RnB_Query/MapServer/1"),
                 ("tg-rb-lanes", f"{TGRAC}/RnB_Folder/RnB_Query/MapServer/2"), ("tg-nh", f"{TGRAC}/RnB_Folder/RnB_Roads/MapServer/1"),
                 ("tg-sh", f"{TGRAC}/RnB_Folder/RnB_Roads/MapServer/3"), ("tg-mdr", f"{TGRAC}/RnB_Folder/RnB_Roads/MapServer/4"),
                 ("tg-odr", f"{TGRAC}/RnB_Folder/RnB_Roads/MapServer/5"), ("tg-rb-lanes-2", f"{TGRAC}/RnB_Folder/RnB_Roads/MapServer/12")])
# Haryana: PWD B&R roads (HSAC, PM Gati Shakti service) and the "Mharisadak_Staging" layer (117,130 roads of all owners, road_catog
# free text). Mharisadak fields hold user login ids (ur_id) and officers' phone numbers and email (*_dlp): stored, never shown.
DIRECT_HR = ("hr-pwd", "Haryana roads: PWD B&R roads and the Mharisadak road register of all owners (HSAC)", "hsacggm.in", 2000, 1000,
             {"fmt": "json"}, [("hr-pwd-roads", "https://hsacggm.in/server/rest/services/PMGatiShakti/Haryana_Roads/MapServer/0"),
                               ("hr-mharisadak", "https://hsacggm.in/server/rest/services/Mharisadak_Staging/mharisadak_roads/MapServer/0")])
# Maharashtra: the only open coded road layer found is the Wardha district works layer (ODR/VR numbers, PWD code) on MRSAC.
DIRECT_MH = ("mh-wardha", "Maharashtra (Wardha district) roads with ODR/VR number and PWD road code (MRSAC)", "gsc.mrsac.org.in", 2000, 1000,
             {"fmt": "json"}, [("mh-wardha-roads", "https://gsc.mrsac.org.in/server/rest/services/mhuid/Works_Department/MapServer/12")])
PROJECTS += [
    {
        "name": f"{FAMILY}-{name}", "title": title, "task": "arcgis", "target": target, "env": {}, "probe": None, "pool": False,
        "unit_label": f"page of up to {size} features", "record_label": "page",
        "items": [{"key": f"count-{layer}", "payload": {"url": url, "name": layer, "size": size, **extra}} for layer, url in layers],
        "workers": 1, "delay_ms": delay,
    }
    for name, title, target, delay, size, extra, layers in [DIRECT_TG, DIRECT_HR, DIRECT_MH]
]

# Tamil Nadu: TNGIS WFS (GeoServer). The layers have no primary key, so pages are sorted by tngis_id (tnrd: id). TNGIS answers
# GitHub runners abroad (civic-officials uses it the same way), so this project is in the pool with no proxy.
TNGIS = "https://tngis.tn.gov.in/tngismaps/wfs"
TN_LAYERS = [
    ("tn-sh", "generic_viewer:state_highways", "tngis_id ASC,object_id ASC"),
    ("tn-mdr", "generic_viewer:major_district_roads", "tngis_id ASC,object_id ASC"),
    ("tn-nh", "generic_viewer:national_highways", "tngis_id ASC,object_id ASC"),
    ("tn-odr", "generic_viewer:other_district_roads", "tngis_id ASC,object_id ASC"),
    ("tn-rural-roads", "tnrd:roads", "id ASC"),
    ("tn-village-roads", "generic_viewer:village_roads", "tngis_id ASC,object_id ASC"),
]
PROJECTS += [{
    "name": f"{FAMILY}-tn", "title": "Tamil Nadu roads with road numbers: NH, SH, MDR, ODR, rural and village roads (TNGIS WFS)",
    "task": "wfs", "target": "tngis.tn.gov.in", "env": {}, "probe": None,
    "unit_label": "page of 500 features", "record_label": "page",
    "items": [{"key": f"count-{name}", "payload": {"url": TNGIS, "type": t, "name": name, "size": 500, "sort": sort}} for name, t, sort in TN_LAYERS],
    "workers": 1, "delay_ms": 2000,
}]

# NHAI Datalake GeoServer WFS (open, no login): the NH network, project alignments with old and new NH numbers and chainage, toll
# plazas, corridors, and accident stretches with start and end chainage. Not tested from abroad, so DIRECT (dev-vps-3).
NHAI = "https://datalakew.nhai.gov.in/geoserver/NHAI/ows"
NHAI_LAYERS = ["nh_network_of_india_new", "india_nh", "toll_plaza", "upc_based_allignment_of_nhai_projects", "upc_wise_alignments_layers",
               "adv_nhai_alignments_layers", "adv_upc_wise_alignments_layers", "bharatmala_corridors", "national_corridors",
               "economic_corridors", "morth_link_projects", "nhai_link_projects", "nhidcl_link_projects", "wayside_amenities",
               "traffic_survey", "Distress_Bridges", "RoadAccident_GIS_Layer"]
PROJECTS += [{
    "name": f"{FAMILY}-nhai", "title": "NHAI Datalake: NH network, project alignments with NH numbers and chainage, toll plazas (WFS)",
    "task": "wfs", "target": "datalakew.nhai.gov.in", "env": {}, "probe": None, "pool": False,
    "unit_label": "page of 500 features", "record_label": "page",
    "items": [{"key": f"count-nhai-{t.lower().replace('_', '-')}", "payload": {"url": NHAI, "type": f"NHAI:{t}", "name": f"nhai-{t.lower().replace('_', '-')}",
                                                                             "size": 500}} for t in NHAI_LAYERS],
    "workers": 1, "delay_ms": 2000,
}]
# Added 2026-11-13 (owner: "download everything"): accident spots, land plots (owner names, survey numbers: stored, never shown),
# and attribute-only copies of three layers whose stored geometry makes the server fail (java.io.IOException). The attribute
# "ae/ie" cannot be requested (the slash breaks the server), so it is left out; start/end lat-long and chainage are kept.
NHAI_ATTR = {
    "NSV_Distress_Data_WMS": "id,objectid,fid_1,start_lat,start_lon,end_lat,end_lon,condition,start_chai,unnamed__6,unnamed__7,color,upc,category,unnamed__8,shape_leng",
    "upc_wise_alignments_layers": "id,upc,length,lane,concession,scheme,mode,piu,ro,state,phase,lane_2,project_ty,project_na,current_st,starting_l,end_latitu,start_long,end_long,nh_new,alignment_id,green_brown_field,parliaments_name",
    "adv_nhai_alignments_layers": "id,upc,length,lane,concession,scheme,mode,piu,ro,state,phase,lane_2,project_ty,project_na,current_st,starting_l,end_latitu,start_long,end_long,nh_new,alignment_id,green_brown_field,parliaments_name,adv_total_capital_cost,adv_cumphysical_progress_tilllastmonth,adv_cumfinancial_progress_tilllastmonth,adv_project_name,adv_lanes,adv_mode,adv_ro_contact_no,adv_pd_contact_no,drone_video_name,adv_appointed_date,adv_scheduled_completion_date,adv_length,loa_date,district_name,adv_pkg_name,nsv_availability",
}
PROJECTS[-1]["items"] += [
    {"key": f"count-nhai-{t.lower().replace('_', '-')}", "payload": {"url": NHAI, "type": f"NHAI:{t}", "name": f"nhai-{t.lower().replace('_', '-')}", "size": 500}}
    for t in ["RoadAccident_Spot_GIS_Layer", "Land_Arbitration_Plot_Layer"]
] + [
    {"key": f"count-nhai-{t.lower().replace('_', '-')}-attrs", "payload": {"url": NHAI, "type": f"NHAI:{t}", "name": f"nhai-{t.lower().replace('_', '-')}-attrs",
                                                                          "size": 500, "sort": "id ASC", "props": props}}
    for t, props in NHAI_ATTR.items()
]

# Kerala: the state GIS hosts do not answer dev-vps-3 (no route / 403 / timeout). One GET per host page from a GitHub runner abroad.
KERALA = ["https://opensdi.kerala.gov.in/", "https://opensdi.kerala.gov.in/api/v2/datasets?page_size=100",
          "https://opensdi.kerala.gov.in/geoserver/ows?service=WFS&version=2.0.0&request=GetCapabilities",
          "https://ksdi.kerala.gov.in/", "https://ksdi.kerala.gov.in/geoserver/ows?service=WFS&request=GetCapabilities",
          "https://geoportal.kerala.gov.in/", "https://geoportal.kerala.gov.in/geoserver/ows?service=WFS&request=GetCapabilities",
          "https://gis.kerala.gov.in/", "https://gis.kerala.gov.in/arcgis/rest/services?f=json", "https://maps.kerala.gov.in/",
          "http://103.35.198.65:8181/kpwd.gis/", "https://keralapwd.gov.in/", "https://www.ksrec.kerala.gov.in/"]
PROJECTS += [{
    "name": f"{FAMILY}-kerala-probe", "title": "Kerala GIS hosts: reachability check from a GitHub runner (one GET each)",
    "task": "probe", "target": "kerala.gov.in", "env": {}, "probe": None,
    "unit_label": "page", "record_label": "check",
    "items": [{"key": f"k{i:02d}", "payload": {"url": u}} for i, u in enumerate(KERALA)],
    "workers": 1, "delay_ms": 2000,
}]

PROBES = [{"name": f"{FAMILY}:livingatlas.esri.in", "url": f"{ESRI_IN}/IN_DRRP_Road_2021/MapServer/0?f=json", "expect": "District Rural Road"}]
