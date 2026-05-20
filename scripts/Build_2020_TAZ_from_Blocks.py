import os
import sys
import geopandas as gpd
import pandas as pd

# -------------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------------

# Inputs
TAZ_2011_SHP = r"J:\TAZ_Adustment\Input\2010GIS\SJTDM Final TAZ_Nov2011.shp"
BLOCKS_2020_SHP = r"J:\TAZ_Adustment\Input\2020GIS\2020_Blocks_Projected_Clipped.shp"

# Outputs
OUT_DIR = r"J:\TAZ_Adustment\Output\Final Draft 2020 TAZs"

OUT_TAZ_2020_SHP = os.path.join(OUT_DIR, "TAZ_2020_fromBlocks.shp")
OUT_UNMATCHED_SHP = os.path.join(OUT_DIR, "TAZ2020_Unmatched_Blocks_geo.shp")
OUT_UNMATCHED_CSV = os.path.join(OUT_DIR, "TAZ2020_Unmatched_Blocks.csv")

# Fields
TAZ_ID_FIELD = "TAZ_112011"
BLOCK_ID_FIELD = "GEOID20"

# -------------------------------------------------------------------
# VALIDATION
# -------------------------------------------------------------------

for path in [TAZ_2011_SHP, BLOCKS_2020_SHP]:
    if not os.path.exists(path):
        sys.exit(f"ERROR: Missing input file: {path}")

os.makedirs(OUT_DIR, exist_ok=True)

# -------------------------------------------------------------------
# LOAD DATA
# -------------------------------------------------------------------

print("Loading 2011 TAZ layer...")
taz = gpd.read_file(TAZ_2011_SHP)
print(f"  -> {len(taz):,} TAZ features")

if TAZ_ID_FIELD not in taz.columns:
    sys.exit(f"ERROR: Required field '{TAZ_ID_FIELD}' not found")

print("Loading 2020 Census Blocks...")
blocks = gpd.read_file(BLOCKS_2020_SHP)
print(f"  -> {len(blocks):,} block features")

if BLOCK_ID_FIELD not in blocks.columns:
    sys.exit(f"ERROR: Required field '{BLOCK_ID_FIELD}' not found")

# -------------------------------------------------------------------
# CRS ALIGNMENT
# -------------------------------------------------------------------

if taz.crs != blocks.crs:
    print("Reprojecting blocks to match TAZ CRS...")
    blocks = blocks.to_crs(taz.crs)

# -------------------------------------------------------------------
# FIELD NORMALIZATION
# -------------------------------------------------------------------

def clean_id(series):
    return (
        series.astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.lstrip("0")
    )

taz[TAZ_ID_FIELD] = clean_id(taz[TAZ_ID_FIELD])
blocks[BLOCK_ID_FIELD] = blocks[BLOCK_ID_FIELD].astype(str)

taz = taz[[TAZ_ID_FIELD, "geometry"]]
blocks = blocks[[BLOCK_ID_FIELD, "geometry"]]

# -------------------------------------------------------------------
# SPATIAL ASSIGNMENT (FIXED)
# -------------------------------------------------------------------

print("Assigning blocks using centroid method...")

# Create centroids
blocks["centroid"] = blocks.geometry.centroid

blocks_cent = gpd.GeoDataFrame(
    blocks[[BLOCK_ID_FIELD]],
    geometry=blocks["centroid"],
    crs=blocks.crs
)

# Spatial join (centroid within TAZ)
blocks_joined = gpd.sjoin(
    blocks_cent,
    taz,
    how="left",
    predicate="within"
)

# Merge TAZ assignment back to full block geometry
blocks = blocks.merge(
    blocks_joined[[BLOCK_ID_FIELD, TAZ_ID_FIELD]],
    on=BLOCK_ID_FIELD,
    how="left"
)
# DROP centroid column (CRITICAL FIX)
blocks = blocks.drop(columns=["centroid"])
# -------------------------------------------------------------------
# SPLIT MATCHED / UNMATCHED
# -------------------------------------------------------------------

matched = blocks[blocks[TAZ_ID_FIELD].notna()].copy()
unmatched = blocks[blocks[TAZ_ID_FIELD].isna()].copy()

print(f"Matched blocks:   {len(matched):,}")
print(f"Unmatched blocks: {len(unmatched):,}")

# -------------------------------------------------------------------
# WRITE UNMATCHED BLOCKS
# -------------------------------------------------------------------

if len(unmatched) > 0:
    print("Writing unmatched blocks for manual assignment...")

    unmatched_geo = unmatched[[BLOCK_ID_FIELD, "geometry"]].copy()
    unmatched_geo["TAZ2020"] = ""

    unmatched_geo["geometry"] = unmatched_geo.buffer(0)

    unmatched_geo.to_file(OUT_UNMATCHED_SHP)
    unmatched_geo[[BLOCK_ID_FIELD]].to_csv(OUT_UNMATCHED_CSV, index=False)

# -------------------------------------------------------------------
# DISSOLVE INTO TAZs
# -------------------------------------------------------------------

print("Dissolving blocks into TAZ polygons...")

taz_2020 = matched.dissolve(
    by=TAZ_ID_FIELD,
    as_index=False
)

# -------------------------------------------------------------------
# GEOMETRY CLEANUP
# -------------------------------------------------------------------

print("Fixing geometries...")
taz_2020["geometry"] = taz_2020.buffer(0)

# -------------------------------------------------------------------
# VALIDATION CHECK (IMPORTANT)
# -------------------------------------------------------------------

print("Validating TAZ uniqueness...")

if not taz_2020[TAZ_ID_FIELD].is_unique:
    raise Exception("ERROR: Duplicate TAZ_IDs after dissolve")

print("TAZ count:", len(taz_2020))

# -------------------------------------------------------------------
# WRITE OUTPUT
# -------------------------------------------------------------------

print("Writing final TAZ shapefile...")
taz_2020.to_file(OUT_TAZ_2020_SHP)

print("--------------------------------------------------")
print("PROCESS COMPLETE")
print(f"Final 2020 TAZs:       {len(taz_2020):,}")
print(f"Unmatched blocks:      {len(unmatched):,}")
print(f"Output:                {OUT_TAZ_2020_SHP}")
print("--------------------------------------------------")