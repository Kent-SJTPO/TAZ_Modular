import os
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyodbc


SETTINGS_DB = (
    r"H:\Planning\SJTDM\FY 2025 Recalibration"
    r"\Demographics\CensusBlocks.accdb"
)

COUNTIES = {
    "34001": "Atlantic",
    "34005": "Burlington",
    "34009": "Cape May",
    "34011": "Cumberland",
    "34015": "Gloucester",
    "34033": "Salem",
}

OUTPUT_LAYER = "Blocks2020_SJTDM_Master"


def get_settings(accdb_path):
    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={accdb_path};"
    )

    conn = pyodbc.connect(conn_str)
    sql = """
        SELECT SettingName, SettingValue
        FROM tblSystemSettings
        WHERE IsActive = True
    """
    rows = conn.execute(sql).fetchall()
    conn.close()

    return {row.SettingName: row.SettingValue for row in rows}


def find_county_block_file(source_root, county_geoid):
    matches = []

    for root, dirs, files in os.walk(source_root):
        for file_name in files:
            low = file_name.lower()
            if (
                file_name.endswith(".shp")
                and county_geoid in file_name
                and ("tabblock" in low or "block" in low)
            ):
                matches.append(Path(root) / file_name)

    if len(matches) == 0:
        raise FileNotFoundError(
            f"No Census block shapefile found for county {county_geoid} "
            f"under {source_root}"
        )

    if len(matches) > 1:
        print(f"Multiple matches found for {county_geoid}:")
        for m in matches:
            print(f"  {m}")
        print("Using first match.")

    return matches[0]


def require_fields(gdf, fields, source_name):
    missing = [f for f in fields if f not in gdf.columns]
    if missing:
        raise ValueError(f"{source_name} is missing required fields: {missing}")


def main():
    print("")
    print("Reading system settings...")

    settings = get_settings(SETTINGS_DB)

    gis_root = Path(settings["GISRoot"])
    master_gdb = Path(settings["MasterGDB"])
    target_crs = settings["TargetCRS"]

    source_root = gis_root / "Source_Census" / "2020_Blocks_By_County"
    qa_root = gis_root / "QA"
    qa_root.mkdir(exist_ok=True)

    print(f"GIS root:     {gis_root}")
    print(f"Source root:  {source_root}")
    print(f"Master GDB:   {master_gdb}")
    print(f"Target CRS:   {target_crs}")
    print("")

    if not source_root.exists():
        raise FileNotFoundError(f"Source folder does not exist: {source_root}")

    if not master_gdb.exists():
        raise FileNotFoundError(f"Master geodatabase does not exist: {master_gdb}")

    required_fields = [
        "GEOID20",
        "STATEFP20",
        "COUNTYFP20",
        "TRACTCE20",
        "BLOCKCE20",
    ]

    all_blocks = []

    for county_geoid, county_name in COUNTIES.items():
        shp_path = find_county_block_file(source_root, county_geoid)

        print(f"Reading {county_name}: {shp_path}")

        gdf = gpd.read_file(shp_path)

        require_fields(gdf, required_fields, str(shp_path))

        gdf["SOURCE_COUNTY"] = county_name
        gdf["SOURCE_FILE"] = str(shp_path)

        print(f"  Records: {len(gdf):,}")

        all_blocks.append(gdf)

    print("")
    print("Combining county block layers...")

    blocks = pd.concat(all_blocks, ignore_index=True)
    blocks = gpd.GeoDataFrame(blocks, geometry="geometry", crs=all_blocks[0].crs)

    print(f"Combined records: {len(blocks):,}")

    print("")
    print("Normalizing GEOID fields...")

    for field in required_fields:
        blocks[field] = blocks[field].astype(str).str.strip()

    blocks["GEOID20_REBUILT"] = (
        blocks["STATEFP20"].str.zfill(2)
        + blocks["COUNTYFP20"].str.zfill(3)
        + blocks["TRACTCE20"].str.zfill(6)
        + blocks["BLOCKCE20"].str.zfill(4)
    )

    print("")
    print("Projecting...")

    blocks = blocks.to_crs(target_crs)

    print("")
    print("Running QA...")

    qa = {}

    qa["total_records"] = len(blocks)
    qa["geoid_length_failures"] = int((blocks["GEOID20"].str.len() != 15).sum())
    qa["geoid_rebuild_mismatches"] = int(
        (blocks["GEOID20"] != blocks["GEOID20_REBUILT"]).sum()
    )
    qa["duplicate_geoids"] = int(blocks.duplicated(subset=["GEOID20"]).sum())
    qa["null_geometry"] = int(blocks.geometry.isna().sum())
    qa["invalid_geometry"] = int((~blocks.geometry.is_valid).sum())

    for key, value in qa.items():
        print(f"{key}: {value:,}")

    bad_records = blocks[
        (blocks["GEOID20"].str.len() != 15)
        | (blocks["GEOID20"] != blocks["GEOID20_REBUILT"])
        | (blocks.duplicated(subset=["GEOID20"], keep=False))
        | (blocks.geometry.isna())
        | (~blocks.geometry.is_valid)
    ].copy()

    qa_csv = qa_root / "Blocks2020_Master_QA_Failures.csv"

    if len(bad_records) > 0:
        bad_records.drop(columns="geometry").to_csv(qa_csv, index=False)
        print(f"QA failures written to: {qa_csv}")
    else:
        print("No QA failures found.")

    if qa["invalid_geometry"] > 0:
        print("Repairing invalid geometry with buffer(0)...")
        blocks["geometry"] = blocks.geometry.buffer(0)

    print("")
    print("Writing master layer to geodatabase...")

    try:
        blocks.to_file(
            master_gdb,
            layer=OUTPUT_LAYER,
            driver="OpenFileGDB",
        )
        print(f"Wrote layer: {master_gdb}\\{OUTPUT_LAYER}")

    except Exception as ex:
        print("")
        print("File geodatabase write failed.")
        print(str(ex))
        print("")
        print("Writing fallback GeoPackage instead.")

        fallback_gpkg = gis_root / "Scratch" / "Blocks2020_SJTDM_Master.gpkg"
        fallback_gpkg.parent.mkdir(exist_ok=True)

        if fallback_gpkg.exists():
            fallback_gpkg.unlink()

        blocks.to_file(
            fallback_gpkg,
            layer=OUTPUT_LAYER,
            driver="GPKG",
        )

        print(f"Wrote fallback layer: {fallback_gpkg}")

    print("")
    print("Done.")


if __name__ == "__main__":
    main()