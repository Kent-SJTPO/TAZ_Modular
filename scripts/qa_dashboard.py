import os
import sys
import geopandas as gpd
import pandas as pd

# ------------------------------------------------------------
# CONFIG (EDIT ONLY IF PATHS CHANGE)
# ------------------------------------------------------------

BLOCKS_ASSIGNED_SHP = r"J:\Data Inventory\SJTDM_TAZ\TAZ2011_Assigned_2020_Blocks.shp"
TAZ2011_PROJECTED_SHP = r"J:\Data Inventory\SJTDM_TAZ\SJTDM Final TAZ_Nov2011 Projected.shp"

OUT_DIR = r"J:\Data Inventory\SJTDM_TAZ"
OUT_TAZ2020_NAME = "TAZ2020_Reassembled_from_Blocks_v1.shp"
OUT_COMPARE_NAME = "TAZ2011_vs_2020_Comparison_v1.shp"

TARGET_CRS = "EPSG:3424"  # NJ State Plane NAD83 US feet

# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def require_exists(path: str) -> None:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing required file: {path}")

def normalize_taz_id(series: pd.Series) -> pd.Series:
    """
    Normalize TAZ identifiers to integer-like strings:
      1026.0 -> "1026"
      "1026" -> "1026"
      NaN -> <NA>
    """
    # Convert to numeric where possible (handles strings and floats)
    s = pd.to_numeric(series, errors="coerce")
    # Use pandas nullable integer to preserve missing values
    s = s.astype("Int64")
    # Return string; keep missing as <NA>
    return s.astype("string")

def delete_shapefile_family(shp_path: str) -> None:
    """
    Delete existing shapefile component files if they exist.
    This avoids silent non-overwrite behavior.
    """
    base, _ = os.path.splitext(shp_path)
    exts = [".shp", ".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx", ".shp.xml"]
    for ext in exts:
        p = base + ext
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                # If locked, leave it; the user will see the lock issue explicitly below
                pass

# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main() -> int:
    print("Reassemble + Compare (SHP only) starting...")
    print("Python:", sys.executable)
    print("Script:", os.path.abspath(__file__))

    require_exists(BLOCKS_ASSIGNED_SHP)
    require_exists(TAZ2011_PROJECTED_SHP)
    if not os.path.isdir(OUT_DIR):
        raise FileNotFoundError(f"Output directory does not exist: {OUT_DIR}")

    out_taz2020 = os.path.join(OUT_DIR, OUT_TAZ2020_NAME)
    out_compare = os.path.join(OUT_DIR, OUT_COMPARE_NAME)

    print("\nInputs:")
    print("  Blocks assigned:", BLOCKS_ASSIGNED_SHP)
    print("  2011 TAZs:", TAZ2011_PROJECTED_SHP)
    print("\nOutputs:")
    print("  2020 TAZs:", out_taz2020)
    print("  Comparison:", out_compare)

    # Load
    print("\nLoading layers...")
    blocks = gpd.read_file(BLOCKS_ASSIGNED_SHP)
    taz11 = gpd.read_file(TAZ2011_PROJECTED_SHP)

    print(f"  Blocks: {len(blocks):,}")
    print(f"  TAZ 2011: {len(taz11):,}")
    if len(taz11) < 100:
        raise RuntimeError("TAZ 2011 layer has too few features; verify you are using the correct shapefile.")

    # Force CRS (do not rely on metadata)
    blocks = blocks.set_crs(TARGET_CRS, allow_override=True)
    taz11 = taz11.set_crs(TARGET_CRS, allow_override=True)
    print("\nCRS:")
    print("  Blocks CRS:", blocks.crs)
    print("  TAZ11 CRS:", taz11.crs)

    # Ensure field exists
    if "TAZ_112011" not in blocks.columns:
        raise RuntimeError("Blocks shapefile is missing required field: TAZ_112011")
    if "TAZ_112011" not in taz11.columns:
        raise RuntimeError("2011 TAZ shapefile is missing required field: TAZ_112011")

    # Normalize join key
    print("\nNormalizing TAZ_112011 join keys...")
    blocks["TAZ_ID"] = normalize_taz_id(blocks["TAZ_112011"])
    taz11["TAZ_ID"] = normalize_taz_id(taz11["TAZ_112011"])

    assigned_blocks = blocks[blocks["TAZ_ID"].notna()].copy()
    print(f"  Blocks with TAZ assignment: {len(assigned_blocks):,} of {len(blocks):,}")

    # Dissolve blocks -> rebuilt 2020 TAZs
    print("\nDissolving blocks to rebuild 2020 TAZs...")
    taz20 = assigned_blocks.dissolve(by="TAZ_ID", as_index=False)

    # Clean geometry
    taz20["geometry"] = taz20.geometry.buffer(0)

    print(f"  Rebuilt TAZ count: {len(taz20):,}")

    # Compute area + centroid XY (feet)
    print("\nComputing metrics (EPSG:3424 feet)...")
    taz11["AREA11"] = taz11.geometry.area
    taz20["AREA20"] = taz20.geometry.area

    cen11 = taz11.geometry.centroid
    cen20 = taz20.geometry.centroid

    taz11["C11_X"] = cen11.x
    taz11["C11_Y"] = cen11.y
    taz20["C20_X"] = cen20.x
    taz20["C20_Y"] = cen20.y

    # Join comparison (keep 2011 geometry for mapping)
    print("\nJoining rebuilt 2020 metrics onto 2011 TAZ geometry...")
    compare = taz11[["TAZ_ID", "geometry", "AREA11", "C11_X", "C11_Y"]].merge(
        taz20[["TAZ_ID", "AREA20", "C20_X", "C20_Y"]],
        on="TAZ_ID",
        how="left"
    )
    compare = gpd.GeoDataFrame(compare, geometry="geometry", crs=TARGET_CRS)

    # Differences
    compare["A_DIF"] = compare["AREA20"] - compare["AREA11"]
    compare["A_PCT"] = (compare["A_DIF"] / compare["AREA11"]) * 100.0
    compare["C_SFT"] = (
        (compare["C20_X"] - compare["C11_X"]) ** 2 +
        (compare["C20_Y"] - compare["C11_Y"]) ** 2
    ) ** 0.5

    # Quick diagnostics
    print("\nDiagnostics:")
    print("  Missing AREA20 (no rebuilt match):", int(compare["AREA20"].isna().sum()))
    print("  Example rows:")
    print(compare[["TAZ_ID", "AREA11", "AREA20", "C_SFT"]].head())

    # Write outputs (delete any existing families first)
    print("\nWriting shapefiles (fresh v1 outputs)...")
    delete_shapefile_family(out_taz2020)
    delete_shapefile_family(out_compare)

    # Keep fields short to avoid truncation surprises in shapefile DBF
    taz20_out = taz20[["TAZ_ID", "AREA20", "C20_X", "C20_Y", "geometry"]].copy()
    compare_out = compare[["TAZ_ID", "AREA11", "AREA20", "A_DIF", "A_PCT", "C_SFT", "C11_X", "C11_Y", "C20_X", "C20_Y", "geometry"]].copy()

    taz20_out.to_file(out_taz2020)
    compare_out.to_file(out_compare)

    # Confirm existence
    print("\nOutput existence check:")
    print("  2020 TAZ shp exists:", os.path.exists(out_taz2020))
    print("  Compare shp exists:", os.path.exists(out_compare))

    print("\nDone.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
