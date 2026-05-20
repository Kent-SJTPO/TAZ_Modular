import geopandas as gpd
import pandas as pd

# -------------------------------------------------------------------
# INPUTS
# -------------------------------------------------------------------

# Block-assigned output from prior step (has TAZ_112011 assigned)
blocks_path = r"J:\Data Inventory\SJTDM_TAZ\TAZ2011_Assigned_2020_Blocks.shp"

# Projected 2011 TAZs in File Geodatabase (WKID 3424 per your screenshot)
taz_gdb_path = r"\\sjtpo-fs.sjtpo.org\users$\Kschellinger\My Documents\ArcGIS\Projects\TAZ Areas\2020 TAZ Projection\2020 TAZ Projection.gdb"
taz_gdb_layer = "SJTDMFinalTAZ_Nov201_Project"  # <-- use EXACT layer name shown in Pro

# -------------------------------------------------------------------
# OUTPUTS (GeoPackage recommended)
# -------------------------------------------------------------------

out_gpkg = r"J:\Data Inventory\SJTDM_TAZ\TAZ2020_Reassembled_and_Comparison.gpkg"
out_layer_taz2020 = "TAZ2020_fromBlocks"
out_layer_compare = "TAZ2011_vs_TAZ2020"

# -------------------------------------------------------------------
# TARGET CRS FOR MEASUREMENTS
# -------------------------------------------------------------------

target_crs = "EPSG:3424"  # NAD83 / New Jersey State Plane (US feet)

# -------------------------------------------------------------------
# LOAD DATA
# -------------------------------------------------------------------

print("Loading block-assigned data...")
blocks = gpd.read_file(blocks_path)

print("Loading projected 2011 TAZs from FileGDB...")
taz_2011 = gpd.read_file(taz_gdb_path, layer=taz_gdb_layer)

# -------------------------------------------------------------------
# REPAIR / NORMALIZE CRS
# -------------------------------------------------------------------
# If a shapefile comes in with crs=None or an ESRI WKT that PROJ can't resolve cleanly,
# explicitly assign EPSG:3424 (allow_override) rather than reprojecting from unknown.
# -------------------------------------------------------------------

if blocks.crs is None:
    print("Blocks CRS is None - assigning EPSG:3424 (allow_override=True)...")
    blocks = blocks.set_crs(target_crs, allow_override=True)
else:
    # Still normalize to ensure PROJ-friendly CRS object
    blocks = blocks.to_crs(target_crs)

if taz_2011.crs is None:
    print("TAZ CRS is None (unexpected for your FGDB) - assigning EPSG:3424 (allow_override=True)...")
    taz_2011 = taz_2011.set_crs(target_crs, allow_override=True)
else:
    taz_2011 = taz_2011.to_crs(target_crs)

print("Blocks CRS:", blocks.crs)
print("TAZ CRS:", taz_2011.crs)

# -------------------------------------------------------------------
# NORMALIZE JOIN KEY TYPE (TAZ ID is an identifier; treat as string)
# -------------------------------------------------------------------

blocks["TAZ_112011"] = blocks["TAZ_112011"].astype(str)
blocks.loc[blocks["TAZ_112011"] == "nan", "TAZ_112011"] = None

taz_2011["TAZ_112011"] = taz_2011["TAZ_112011"].astype(str)

# -------------------------------------------------------------------
# REASSEMBLE 2020 TAZs FROM 2020 BLOCKS (DISSOLVE)
# -------------------------------------------------------------------

print("Reassembling 2020 TAZs from blocks (dissolve)...")

taz_2020 = (
    blocks
    .dropna(subset=["TAZ_112011"])
    .dissolve(by="TAZ_112011", as_index=False)
)

# Clean geometry (self-intersections etc.)
taz_2020["geometry"] = taz_2020.geometry.buffer(0)

# -------------------------------------------------------------------
# CALCULATE AREA + CENTROID COORDS (FEET)
# -------------------------------------------------------------------

print("Calculating areas and centroids (EPSG:3424 feet)...")

taz_2011 = taz_2011.set_geometry("geometry")
taz_2020 = taz_2020.set_geometry("geometry")

taz_2011["AREA11"] = taz_2011.geometry.area
taz_2020["AREA20"] = taz_2020.geometry.area

cen11 = taz_2011.geometry.centroid
cen20 = taz_2020.geometry.centroid

taz_2011["CEN11_X"] = cen11.x
taz_2011["CEN11_Y"] = cen11.y
taz_2020["CEN20_X"] = cen20.x
taz_2020["CEN20_Y"] = cen20.y

# -------------------------------------------------------------------
# JOIN FOR COMPARISON
# -------------------------------------------------------------------

print("Joining 2011 and 2020 by TAZ_112011...")

compare = taz_2011[["TAZ_112011", "geometry", "AREA11", "CEN11_X", "CEN11_Y"]].merge(
    taz_2020[["TAZ_112011", "AREA20", "CEN20_X", "CEN20_Y"]],
    on="TAZ_112011",
    how="left"
)

compare = gpd.GeoDataFrame(compare, geometry="geometry", crs=target_crs)

# Differences
compare["AREA_DIF"] = compare["AREA20"] - compare["AREA11"]
compare["AREA_PCT"] = (compare["AREA_DIF"] / compare["AREA11"]) * 100.0

compare["CEN_SFT"] = (
    (compare["CEN20_X"] - compare["CEN11_X"]) ** 2 +
    (compare["CEN20_Y"] - compare["CEN11_Y"]) ** 2
) ** 0.5

# -------------------------------------------------------------------
# QUICK SANITY CHECKS (PRINT)
# -------------------------------------------------------------------

print("Sanity checks (first 5 AREA11, AREA20, CEN_SFT):")
print(compare[["TAZ_112011", "AREA11", "AREA20", "CEN_SFT"]].head())

zero_area11 = (compare["AREA11"].fillna(0) == 0).sum()
zero_area20 = (compare["AREA20"].fillna(0) == 0).sum()

print("--------------------------------------------------")
print("TAZ count (2011):", len(taz_2011))
print("TAZ count (2020 from blocks):", len(taz_2020))
print("Zero AREA11 rows:", zero_area11)
print("Zero AREA20 rows:", zero_area20)
print("--------------------------------------------------")

# -------------------------------------------------------------------
# WRITE OUTPUTS (GeoPackage avoids shapefile limitations)
# -------------------------------------------------------------------

print("Writing outputs to GeoPackage...")
taz_2020.to_file(out_gpkg, layer=out_layer_taz2020, driver="GPKG")
compare.to_file(out_gpkg, layer=out_layer_compare, driver="GPKG")

print("Done.")
print("Output GeoPackage:", out_gpkg)
print("Layers:", out_layer_taz2020, ",", out_layer_compare)
