import geopandas as gpd
import pandas as pd

# -------------------------------------------------------------------
# FILE PATHS
# -------------------------------------------------------------------


taz_path = r"J:\Data Inventory\SJTDM_TAZ\SJTDM Final TAZ_Nov2011.shp"
blocks_path = r"J:\Data Inventory\Census\Census_2020\Census_Blocks_2020\2020_Blocks_Projected_Clipped.shp"

output_path = r"J:\Data Inventory\SJTDM_TAZ\TAZ2011_Assigned_2020_Blocks.shp"

# -------------------------------------------------------------------
# LOAD DATA
# -------------------------------------------------------------------

print("Loading data...")
taz = gpd.read_file(taz_path)
blocks = gpd.read_file(blocks_path)

# -------------------------------------------------------------------
# CRS CHECK
# ------------------------------------------------------------------

if taz.crs != blocks.crs:
    taz = taz.to_crs(blocks.crs)

# -------------------------------------------------------------------
# PREP OUTPUT
# -------------------------------------------------------------------

blocks_out = blocks.copy()
blocks_out["TAZ_112011"] = None
blocks_out["ASSIGN_METHOD"] = None  # CONTAINED | DOMINANT_AREA

# -------------------------------------------------------------------
# PASS 1 - FULL CONTAINMENT
# -------------------------------------------------------------------

print("Pass 1: full containment test...")

contained = gpd.sjoin(
    blocks_out,
    taz[["TAZ_112011", "geometry"]],
    how="left",
    predicate="within"
)

# Identify the joined TAZ field safely
taz_join_field = "TAZ_112011_right"

if taz_join_field not in contained.columns:
    raise RuntimeError("Expected joined TAZ field not found after spatial join.")

contained_valid = contained[contained[taz_join_field].notna()].copy()

blocks_out.loc[contained_valid.index, "TAZ_112011"] = contained_valid[taz_join_field]
blocks_out.loc[contained_valid.index, "ASSIGN_METHOD"] = "CONTAINED"

print(f"Assigned by containment: {len(contained_valid)}")

# -------------------------------------------------------------------
# PASS 2 — DOMINANT AREA (REMAINDER)
# -------------------------------------------------------------------

print("Pass 2: dominant area assignment...")

remaining = blocks_out[blocks_out["TAZ_112011"].isna()]

dominant_assigned = 0

for idx, blk in remaining.iterrows():
    candidates = taz[taz.intersects(blk.geometry)]

    if candidates.empty:
        continue

    areas = candidates.geometry.intersection(blk.geometry).area
    best_idx = areas.idxmax()

    if areas.loc[best_idx] > 0:
        blocks_out.at[idx, "TAZ_112011"] = candidates.loc[best_idx, "TAZ_112011"]
        blocks_out.at[idx, "ASSIGN_METHOD"] = "DOMINANT_AREA"
        dominant_assigned += 1

print(f"Assigned by dominant area: {dominant_assigned}")

# -------------------------------------------------------------------
# SUMMARY
# -------------------------------------------------------------------

print("--------------------------------------------------")
print(f"Total blocks:        {len(blocks_out)}")
print(f"Contained assigned:  {(blocks_out['ASSIGN_METHOD'] == 'CONTAINED').sum()}")
print(f"Area assigned:       {(blocks_out['ASSIGN_METHOD'] == 'DOMINANT_AREA').sum()}")
print(f"Unassigned blocks:   {blocks_out['TAZ_112011'].isna().sum()}")
print("--------------------------------------------------")

# -------------------------------------------------------------------
# WRITE OUTPUT
# -------------------------------------------------------------------

print(f"Writing output to:\n{output_path}")
blocks_out.to_file(output_path)

print("Done.")

