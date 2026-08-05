"""Generate the demo app's STAC collection from the actual assets."""
import json, os
import rasterio, geopandas as gpd

BASE = "https://schmidtdse.github.io/jotr-fire-explorer"
APP = "/tmp/jotr-app"

rasters = {}
for fire, label, date in [("eureka", "Eureka", "2025-05"), ("black-rock", "Black Rock", "2025-10")]:
    with rasterio.open(f"{APP}/data/{fire}-rbr-cog.tif") as s:
        a = s.read(1, masked=True)
        rasters[fire] = dict(label=label, date=date, bounds=list(s.bounds), w=s.width, h=s.height,
                             vmin=float(a.min()), vmax=float(a.max()), n=int(a.count()),
                             nodata=s.nodata)

veg = gpd.read_parquet(f"{APP}/data/jotr-vegetation.parquet")
vb = [round(float(v), 4) for v in veg.total_bounds]

allb = [min(vb[0], *[r["bounds"][0] for r in rasters.values()]),
        min(vb[1], *[r["bounds"][1] for r in rasters.values()]),
        max(vb[2], *[r["bounds"][2] for r in rasters.values()]),
        max(vb[3], *[r["bounds"][3] for r in rasters.values()])]

VEG_COLS = [
    {"name": "Poly_ID", "type": "int64", "description": "Source polygon identifier from the NPS vegetation map."},
    {"name": "MapUnit_ID", "type": "int64", "description": "Numeric code for the vegetation map unit."},
    {"name": "MapUnit_Name", "type": "string",
     "description": "Vegetation map unit name, e.g. 'Singleleaf Pinyon / Muller Oak Woodland Association'. 67 distinct units across the park. This is the column to group by for vegetation breakdowns."},
    {"name": "Hectares", "type": "float64",
     "description": "Polygon area in hectares as published by NPS. Prefer this over recomputing area from geometry."},
    {"name": "geometry", "type": "geometry",
     "description": "POLYGON/MULTIPOLYGON in WGS84 (OGC:CRS84), i.e. longitude, latitude."},
]


def rbr_asset(fire, r):
    return {
        "href": f"{BASE}/data/{fire}-rbr-cog.tif",
        "type": "image/tiff; application=geotiff; profile=cloud-optimized",
        "title": f"{r['label']} Fire — Relativized Burn Ratio (RBR)",
        "roles": ["data"],
        "description": (
            f"Relativized Burn Ratio for the {r['label']} Fire ({r['date']}), "
            f"{r['w']}x{r['h']} pixels at roughly 15 m, {r['n']:,} valid pixels, "
            f"observed range {r['vmin']:.3f} to {r['vmax']:.3f}, nodata {r['nodata']:g}. "
            "RBR = dNBR / (NBR_prefire + 1.001) after Parks, Dillon & Miller (2014). "
            "Higher is more severe; values at or below 0 indicate no detected change. "
            "Produced by the Schmidt DSE Fire Severity Tool."
        ),
        "raster:bands": [{"name": "rbr", "data_type": "float32", "nodata": r["nodata"],
                          "unit": "dimensionless"}],
    }


collection = {
    "type": "Collection",
    "id": "jotr-fire-severity",
    "stac_version": "1.0.0",
    "stac_extensions": [
        "https://stac-extensions.github.io/table/v1.2.0/schema.json",
        "https://stac-extensions.github.io/raster/v1.1.0/schema.json",
    ],
    "title": "Joshua Tree NP Fire Severity & Vegetation",
    "description": (
        "Burn severity rasters for the 2025 Eureka and Black Rock fires in Joshua Tree "
        "National Park, together with the park-wide NPS vegetation map. Supports the "
        "post-fire reporting questions NPS asks after a burn: how much area burned, in "
        "which vegetation types, at what severity, and how much of it had burned before. "
        "Historical fire perimeters are not included here — use the CAL FIRE collections "
        "in the public catalog (calfire-2025-firep), which already contain both 2025 fires "
        "and every prior perimeter in the park."
    ),
    "license": "CC-BY-4.0",
    "extent": {
        "spatial": {"bbox": [[round(v, 4) for v in allb]]},
        "temporal": {"interval": [["2025-05-01T00:00:00Z", "2025-10-31T23:59:59Z"]]},
    },
    "providers": [
        {"name": "Schmidt Center for Data Science & Environment, UC Berkeley",
         "roles": ["producer", "processor"], "url": "https://dse.berkeley.edu"},
        {"name": "National Park Service", "roles": ["producer"],
         "url": "https://irma.nps.gov/DataStore/Reference/Profile/2233319"},
    ],
    "assets": {
        "eureka-rbr": rbr_asset("eureka", rasters["eureka"]),
        "black-rock-rbr": rbr_asset("black-rock", rasters["black-rock"]),
        "vegetation-pmtiles": {
            "href": f"{BASE}/data/jotr-vegetation.pmtiles",
            "type": "application/vnd.pmtiles",
            "title": "JOTR Vegetation Map (PMTiles)",
            "roles": ["visual"],
            "description": f"{len(veg):,} vegetation polygons, zoom 6-14, for map display.",
            "vector:layers": ["vegetation"],
            "table:columns": [c for c in VEG_COLS if c["name"] != "geometry"],
        },
        "vegetation-parquet": {
            "href": f"{BASE}/data/jotr-vegetation.parquet",
            "type": "application/x-parquet",
            "title": "JOTR Vegetation Map (GeoParquet)",
            "roles": ["data"],
            "description": (
                f"DuckDB-native GeoParquet, {len(veg):,} polygons covering "
                f"{veg.Hectares.sum():,.0f} ha, {veg.MapUnit_Name.nunique()} map units, "
                "POLYGON/MULTIPOLYGON in WGS84 (OGC:CRS84). Vegetation Mapping Inventory "
                "Project for Joshua Tree NP (NPS). Coordinates are snapped to a 1e-6 degree "
                "(~0.1 m) grid to reduce file size; this is far below the mapping accuracy "
                "of the source and does not change reported areas."
            ),
            "table:columns": VEG_COLS,
        },
    },
    "links": [
        {"rel": "self", "href": f"{BASE}/stac/collection.json", "type": "application/json"},
        {"rel": "about", "href": "https://github.com/SchmidtDSE/jotr_2025_fire_eda",
         "type": "text/html", "title": "Source R analysis this app is derived from"},
    ],
}

os.makedirs(f"{APP}/stac", exist_ok=True)
with open(f"{APP}/stac/collection.json", "w") as f:
    json.dump(collection, f, indent=2)
    f.write("\n")

print(f"wrote stac/collection.json  bbox={collection['extent']['spatial']['bbox'][0]}")
for k, v in rasters.items():
    print(f"  {k}: {v['w']}x{v['h']}, {v['n']:,} px, {v['vmin']:.3f}..{v['vmax']:.3f}")
print(f"  vegetation: {len(veg):,} polys, {veg.MapUnit_Name.nunique()} units, {veg.Hectares.sum():,.0f} ha")
