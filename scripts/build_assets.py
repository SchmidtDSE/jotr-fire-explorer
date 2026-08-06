"""Build the demo app's data assets: COGs for the RBR rasters, PMTiles + GeoParquet
for the JOTR vegetation polygons."""
import os, subprocess, json
import geopandas as gpd
from shapely import set_precision
from rio_cogeo.cogeo import cog_translate, cog_validate
from rio_cogeo.profiles import cog_profiles

SRC = "/tmp/jotr_eda"
OUT = "/tmp/jotr_demo_assets"
os.makedirs(OUT, exist_ok=True)


def mb(p):
    return f"{os.path.getsize(p)/1e6:.1f} MB"


# --- 1. RBR rasters -> COG -------------------------------------------------
# Tiny rasters, so overviews barely matter; do it anyway so titiler gets a
# well-formed COG and the STAC asset type is honest.
for fire in ("eureka", "black_rock"):
    src = f"{SRC}/fires/{fire}/inputs/refined_rbr.tif"
    dst = f"{OUT}/{fire.replace('_', '-')}-rbr-cog.tif"
    cog_translate(src, dst, cog_profiles.get("deflate"), overview_resampling="bilinear",
                  quiet=True, web_optimized=False)
    valid, errs, warns = cog_validate(dst)
    print(f"COG {fire:11} {mb(dst):>9}  valid={valid}  errors={errs or 'none'}")

# --- 2. Vegetation polygons ------------------------------------------------
veg = gpd.read_file(f"{SRC}/shared_inputs/jotrgeodata.gpkg", layer="JOTR_VegPolys").to_crs(4326)

# Join the NVCS classification hierarchy shipped with the geodatabase. 67 map units
# is far more than a legend can carry, so the map colors by NVCS Group — the
# published rollup — rather than by anything parsed out of the unit names.
nvcs = gpd.read_file(f"{SRC}/shared_inputs/jotrgeodata.gpkg",
                     layer="JOTR_tMapUnit_NVCS2", ignore_geometry=True)
veg = veg.merge(nvcs[["MapUnitID", "Class", "Macrogroup", "Groups"]],
                left_on="MapUnit_ID", right_on="MapUnitID", how="left")
assert veg["Groups"].notna().all(), "every polygon must carry an NVCS Group"

# Five colored classes + Other. Five is the most the data-viz all-pairs gates admit
# for a choropleth (six fails the normal-vision floor at ΔE 12.6 < 15), so the
# ranking is by park-wide area and the tail folds into Other — 5.2% across 7 groups.
GROUP_CODES = {
    "Sonoran-Mojave Creosotebush - White Bursage Desert Scrub": 1,
    "Mojave Mid-Elevation Mixed Desert Scrub": 2,
    "North American Warm Desert Dunes & Sand Flats": 3,
    "Great Basin Pinyon - Juniper Woodland": 4,
    "Sonoran-Coloradan Semi-Desert Wash Woodland / Scrub": 5,
}
veg["veg_grp"] = veg["Groups"].map(GROUP_CODES).fillna(9).astype("int16")

_top = veg.groupby("veg_grp").Hectares.sum().sort_values(ascending=False)
print("veg_grp areas (9 = Other):")
for k, v in _top.items():
    print(f"   {k}  {v:10,.0f} ha  {100*v/veg.Hectares.sum():5.1f}%")

veg = veg[["Poly_ID", "MapUnit_ID", "MapUnit_Name", "Hectares",
           "Class", "Macrogroup", "Groups", "veg_grp", "geometry"]].copy()

# Snap coordinates to a 1e-6 degree grid (~0.1 m). Far below the mapping accuracy
# of the source polygons, so reported hectares are unaffected, but it collapses
# float64 noise and compresses much better than the raw coordinates.
veg["geometry"] = set_precision(veg.geometry.values, 1e-6)
veg = veg[~veg.geometry.is_empty & veg.geometry.notna()]

pq = f"{OUT}/jotr-vegetation.parquet"
veg.to_parquet(pq, compression="zstd", write_covering_bbox=False)


def drop_geoparquet_crs(path):
    """Remove the `crs` key from the GeoParquet metadata so the column reads as
    OGC:CRS84 (the spec default when `crs` is absent) rather than EPSG:4326.

    Both describe the same lon/lat WKB, but DuckDB types them differently and then
    refuses ST_Contains across the two — so a file stamped EPSG:4326 cannot be
    joined to the catalog's collections, which all omit the key. The coordinates
    are untouched; only the metadata changes.
    """
    import pyarrow.parquet as pq_, json as _json
    t = pq_.read_table(path)
    md = dict(t.schema.metadata or {})
    geo = _json.loads(md[b"geo"])
    for col in geo.get("columns", {}).values():
        col.pop("crs", None)
    md[b"geo"] = _json.dumps(geo).encode()
    pq_.write_table(t.replace_schema_metadata(md), path, compression="zstd")


drop_geoparquet_crs(pq)
print(f"\nGeoParquet  {mb(pq):>9}  {len(veg):,} features, {veg.MapUnit_Name.nunique()} map units")

import pyarrow.parquet as _pq
_geo = json.loads(_pq.read_schema(pq).metadata[b"geo"])
_col = _geo["columns"][_geo["primary_column"]]
print(f"  geoparquet v{_geo['version']}, crs key present: {'crs' in _col} "
      f"(absent => OGC:CRS84, matching the catalog)")

# area check against the source column — precision snapping must not move it
a = veg.to_crs(26911).area.sum() / 1e4
print(f"area check: sum(Hectares)={veg.Hectares.sum():,.1f} ha vs geometry={a:,.1f} ha "
      f"({100*abs(a-veg.Hectares.sum())/veg.Hectares.sum():.3f}% diff)")

# --- 3. PMTiles for the map ------------------------------------------------
gj = f"{OUT}/veg.geojsonl"
veg.to_file(gj, driver="GeoJSONSeq")
pmt = f"{OUT}/jotr-vegetation.pmtiles"
subprocess.run([
    "tippecanoe", "-o", pmt, "--force",
    "--layer=vegetation",
    "-y", "Poly_ID", "-y", "MapUnit_Name", "-y", "Hectares", "-y", "veg_grp", "-y", "Groups",
    "-Z6", "-z14",                      # park-wide overview through fire-scale detail
    "--drop-densest-as-needed",
    "--extend-zooms-if-still-dropping",
    "--no-tile-size-limit",
    gj,
], check=True, capture_output=True)
os.remove(gj)
print(f"PMTiles     {mb(pmt):>9}")

print("\n--- assets ---")
for f in sorted(os.listdir(OUT)):
    print(f"  {f:34} {mb(os.path.join(OUT, f)):>9}")
