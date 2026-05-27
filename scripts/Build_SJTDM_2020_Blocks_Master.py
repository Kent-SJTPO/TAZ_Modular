# Build_SJTDM_2020_Blocks_Master.py
#
# Purpose:
# Create a clean, canonical 2020 Census block master layer for SJTDM.
#
# Key principles:
# - Uses original Census county block shapefiles
# - Avoids clipping
# - Avoids shapefile outputs
# - Preserves Census GEOID integrity
# - Outputs to File Geodatabase
# - Performs QA checks
#
# Recommended execution environment:
# conda activate taz_modular
#
# Author: Kent Schellinger / ChatGPT
# ---------------------------------------------------------------------

import os
import sys
import geopandas as gpd
import pandas as pd

# ---------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------

INPUT_FOLDER = r"J:\Data Inventory\Census\Census_2020\Original_Counties"

COUNTY_FILES = [
    "tl_2020_34001_tabblock20.shp",   # Atlantic
    "tl_2020_34005_tabblock20.shp",   # Burlington
    "tl_2020_34015_tabblock20.shp",   # Gloucester
    "tl_2020_34009_tabblock20.shp",   # Cape May
    "tl_2020_34011_tabblock20.shp",   # Cumberland
    "tl_2020_34033_tabblock20.shp"    # Salem
]

OUTPUT_GPKG = (
    r"C:\Users\Kschellinger\SJTPO_Git\TAZ_Modular\data"
    r"\Blocks2020_SJTDM_Master.gpkg"
)

OUTPUT_LAYER = "Blocks2020_SJTDM_Master"

TARGET_CRS = "EPSG:3424"
# NAD83 New Jersey State Plane Feet

# ---------------------------------------------------------------------
# LOAD COUNTY FILES
# ---------------------------------------------------------------------

gdf_list = []

print("\nLoading county Census block layers...\n")

for shp in COUNTY_FILES:

    full_path = os.path.join(INPUT_FOLDER, shp)

    print(f"Reading: {full_path}")

    gdf = gpd.read_file(full_path)

    print(f"  Records: {len(gdf):,}")

    gdf_list.append(gdf)

# ---------------------------------------------------------------------
# MERGE
# ---------------------------------------------------------------------

print("\nMerging counties...")

blocks = pd.concat(gdf_list, ignore_index=True)

blocks = gpd.GeoDataFrame(blocks, geometry="geometry")

print(f"Combined records: {len(blocks):,}")

# ---------------------------------------------------------------------
# PROJECT
# ---------------------------------------------------------------------

print("\nProjecting to NJ State Plane Feet...")

blocks = blocks.to_crs(TARGET_CRS)

# ---------------------------------------------------------------------
# CLEAN FIELD TYPES
# ---------------------------------------------------------------------

print("\nNormalizing Census fields...")

TEXT_FIELDS = [
    "GEOID20",
    "STATEFP20",
    "COUNTYFP20",
    "TRACTCE20",
    "BLOCKCE20"
]

for fld in TEXT_FIELDS:

    blocks[fld] = (
        blocks[fld]
        .astype(str)
        .str.strip()
    )

# ---------------------------------------------------------------------
# REBUILD GEOID20 FOR QA
# ---------------------------------------------------------------------

print("\nRebuilding GEOID20 for validation...")

blocks["GEOID20_REBUILT"] = (
    blocks["STATEFP20"].str.zfill(2) +
    blocks["COUNTYFP20"].str.zfill(3) +
    blocks["TRACTCE20"].str.zfill(6) +
    blocks["BLOCKCE20"].str.zfill(4)
)

# ---------------------------------------------------------------------
# QA CHECKS
# ---------------------------------------------------------------------

print("\nRunning QA checks...\n")

# GEOID length
bad_length = blocks[
    blocks["GEOID20"].str.len() != 15
]

print(f"GEOID length failures: {len(bad_length):,}")

# GEOID mismatch
bad_match = blocks[
    blocks["GEOID20"] != blocks["GEOID20_REBUILT"]
]

print(f"GEOID rebuild mismatches: {len(bad_match):,}")

# Duplicate GEOIDs
dupes = blocks[
    blocks.duplicated(subset=["GEOID20"], keep=False)
]

print(f"Duplicate GEOIDs: {len(dupes):,}")

# Null geometry
null_geom = blocks[
    blocks.geometry.isnull()
]

print(f"Null geometry records: {len(null_geom):,}")

# Invalid geometry
invalid_geom = blocks[
    ~blocks.geometry.is_valid
]

print(f"Invalid geometry records: {len(invalid_geom):,}")

# ---------------------------------------------------------------------
# OPTIONAL REPAIR
# ---------------------------------------------------------------------

if len(invalid_geom) > 0:

    print("\nRepairing invalid geometry using buffer(0)...")

    blocks["geometry"] = blocks.buffer(0)

# ---------------------------------------------------------------------
# EXPORT
# ---------------------------------------------------------------------

print("\nWriting GeoPackage output...\n")

if os.path.exists(OUTPUT_GPKG):
    os.remove(OUTPUT_GPKG)

blocks.to_file(
    OUTPUT_GPKG,
    layer=OUTPUT_LAYER,
    driver="GPKG"
)

print("Output complete:")
print(OUTPUT_GPKG)

# ---------------------------------------------------------------------
# FINAL SUMMARY
# ---------------------------------------------------------------------

print("\nQA SUMMARY")
print("-" * 60)

print(f"Final block count:           {len(blocks):,}")
print(f"GEOID length failures:       {len(bad_length):,}")
print(f"GEOID rebuild mismatches:    {len(bad_match):,}")
print(f"Duplicate GEOIDs:            {len(dupes):,}")
print(f"Null geometry records:       {len(null_geom):,}")
print(f"Invalid geometry records:    {len(invalid_geom):,}")

print("\nDone.\n")