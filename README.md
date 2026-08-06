# Joshua Tree Fire Explorer

An agent-driven map for exploring fire severity in Joshua Tree National Park. Ask in
plain language — "how much of the Eureka Fire had burned before?", "which vegetation
type burned most severely?" — and the agent writes the SQL, runs it, and puts the
answer on the map.

**Live app:** https://schmidtdse.github.io/jotr-fire-explorer/

This is an exploration layer over the analysis in
[SchmidtDSE/jotr_2025_fire_eda](https://github.com/SchmidtDSE/jotr_2025_fire_eda),
which remains the authoritative source for post-fire reporting numbers. That
repository answers seven fixed questions in R; this app answers arbitrary ones against
the same data.

## Data

| Asset | What it is |
|---|---|
| `data/eureka-rbr-cog.tif` | Eureka Fire (May 2025) burn severity, 92×81 px, 3,835 valid pixels |
| `data/black-rock-rbr-cog.tif` | Black Rock Fire (Oct 2025) burn severity, 57×47 px, 1,138 valid pixels |
| `data/jotr-vegetation.parquet` | NPS vegetation map, 16,499 polygons, 67 map units, 320,788 ha |
| `data/jotr-vegetation.pmtiles` | Same polygons as vector tiles, for map display |
| `stac/collection.json` | STAC collection describing all of the above |

Two more layers come from the public NRP catalog rather than being vendored here:

- **CAL FIRE 2025 fire perimeters** — already contains both 2025 fires and every prior
  perimeter in the park.
- **CWHR habitat types** (`cwhr`) — CAL FIRE FVEG, a 30 m statewide raster in the 60+
  class California Wildlife Habitat Relationships classification, drawn with its STAC
  `classification:classes` colors.

CWHR and the NPS map units are two different classifications of the same ground, built
by different methods at different times; they disagree, and the system prompt tells the
agent to keep them apart. CWHR's native hex is h10 (~1.5 ha), so the whole Eureka Fire
is only ~58 cells — it is context for the wider landscape, not a tool for fire-scale
severity breakdowns.

Severity is the **Relativized Burn Ratio** (RBR), `dNBR / (NBR_prefire + 1.001)`, after
[Parks, Dillon & Miller 2014](https://doi.org/10.3390/rs6031827). Higher is more
severe; values at or below zero indicate no detected change. RBR is preferred over
RdNBR here because RdNBR destabilises where pre-fire NBR approaches zero, which is the
normal condition in sparse Mojave vegetation.

Rasters are from the Schmidt DSE Fire Severity Tool. Vegetation polygons are from the
NPS [Vegetation Mapping Inventory Project for JOTR](https://irma.nps.gov/DataStore/Reference/Profile/2233319).
Vegetation coordinates are snapped to a 1e-6 degree (~0.1 m) grid to reduce file size;
this is well below the mapping accuracy of the source and does not change reported
areas.

## Architecture

Everything is static. GitHub Pages serves the HTML, the config, the STAC collection
and the data; the app loads the geo-agent core from CDN; queries go to a DuckDB MCP
server.

> ⚠️ **This app points at an experimental MCP endpoint**
> (`experimental-duckdb-mcp.nrp-nautilus.io`), not the production one. The severity
> rasters are read live with DuckDB's `raster` community extension (`RT_ReadCells`)
> rather than being pre-aggregated to an H3 hex grid, and that extension is only
> present on the experimental image. **That endpoint carries no uptime guarantee.**
> If the app can answer questions about vegetation but not severity, it is the first
> thing to check.
>
> This works because these fires are tiny — a few thousand pixels each. It is not the
> pattern for a large raster, which should go through the
> [data-workflows](https://github.com/boettiger-lab/data-workflows) hex pipeline
> instead.

## Configuration

Three files, no JavaScript:

- `index.html` — shell; loads geo-agent from CDN, pinned to a release tag
- `layers-input.json` — which collections and assets to show, map view, MCP endpoint
- `system-prompt.md` — domain context and guardrails for the agent

See the [geo-agent docs](https://boettiger-lab.github.io/geo-agent/) for the full
configuration reference.

## Rebuilding the data assets

`scripts/build_assets.py` regenerates the COGs, GeoParquet and PMTiles from the source
repository; `scripts/make_stac.py` regenerates the STAC collection from whatever assets
are on disk, so its pixel counts, value ranges and bounds cannot drift from the files
they describe.

```bash
git clone https://github.com/SchmidtDSE/jotr_2025_fire_eda /tmp/jotr_eda
python scripts/build_assets.py     # writes /tmp/jotr_demo_assets — copy into data/
python scripts/make_stac.py        # writes stac/collection.json
```

Requires `geopandas`, `rasterio`, `rio-cogeo` and `tippecanoe`.
