# Build_SJTDM_2020_Blocks_Master.py

import os
import shutil
import zipfile
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyodbc


SETTINGS_DB = (
    r"H:\Planning\SJTDM\FY 2025 Recalibration"
    r"\Demographics\CensusBlocks.accdb"
)

OUTPUT_LAYER = "Blocks2020_SJTDM_Master"

TARGET_COUNTIES = [
    "001",  # Atlantic
    "005",  # Burlington
    "009",  # Cape May
    "011",  # Cumberland
    "015",  # Gloucester
    "033",  # Salem
]

NJ_BLOCK_URL = (
    "https://www2.census.gov/geo/tiger/TIGER2020/"
    "TABBLOCK20/tl_2020_34_tabblock20.zip"
)

REQUIRED_FIELDS = [
    "GEOID20",
    "STATEFP20",
    "COUNTYFP20",
    "TRACTCE20",
    "BLOCKCE20",
]


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

    return {
        row.SettingName: row.SettingValue
        for row in rows
    }


def prepare_folder(folder_path):
    folder_path.mkdir(parents=True, exist_ok=True)


def download_file(url, output_path):

    print(f"Downloading:\n{url}\n")

    urllib.request.urlretrieve(url, output_path)

    print(f"Saved:\n{output_path}\n")


def extract_zip(zip_path, extract_folder):

    print(f"Extracting:\n{zip_path}\n")

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_folder)


def require_fields(gdf, fields):

    missing = [
        field for field in fields
        if field not in gdf.columns
    ]

    if missing:
        raise ValueError(
            f"Missing required fields: {missing}"
        )


def main():

    print("")
    print("Reading system settings...")

    settings = get_settings(SETTINGS_DB)

    gis_root = Path(settings["GISRoot"])
    master_gdb = Path(settings["MasterGDB"])
    target_crs = settings["TargetCRS"]

    source_root = (
        gis_root /
        "Source_Census" /
        "2020_Blocks_Statewide"
    )

    qa_root = gis_root / "QA"
    scratch_root = gis_root / "Scratch"

    prepare_folder(source_root)
    prepare_folder(qa_root)
    prepare_folder(scratch_root)

    print(f"GIS root:     {gis_root}")
    print(f"Source root:  {source_root}")
    print(f"Master GDB:   {master_gdb}")
    print(f"Target CRS:   {target_crs}")
    print("")

    if not master_gdb.exists():
        raise FileNotFoundError(
            f"Master geodatabase does not exist:\n{master_gdb}"
        )

    zip_path = (
        source_root /
        "tl_2020_34_tabblock20.zip"
    )

    extract_folder = (
        source_root /
        "tl_2020_34_tabblock20"
    )

    shp_path = (
        extract_folder /
        "tl_2020_34_tabblock20.shp"
    )

    if not shp_path.exists():

        if extract_folder.exists():
            shutil.rmtree(extract_folder)

        extract_folder.mkdir(parents=True)

        download_file(NJ_BLOCK_URL, zip_path)

        extract_zip(zip_path, extract_folder)

    if not shp_path.exists():
        raise FileNotFoundError(
            f"Statewide shapefile not found:\n{shp_path}"
        )

    print("Reading statewide Census block layer...\n")

    blocks = gpd.read_file(shp_path)

    require_fields(blocks, REQUIRED_FIELDS)

    print(f"Statewide records: {len(blocks):,}")

    print("")
    print("Filtering SJTDM counties...")

    blocks["COUNTYFP20"] = (
        blocks["COUNTYFP20"]
        .astype(str)
        .str.zfill(3)
    )

    blocks = blocks[
        blocks["COUNTYFP20"].isin(TARGET_COUNTIES)
    ].copy()

    print(f"SJTDM records: {len(blocks):,}")

    print("")
    print("Normalizing GEOID fields...")

    for field in REQUIRED_FIELDS:

        blocks[field] = (
            blocks[field]
            .astype(str)
            .str.strip()
        )

    blocks["GEOID20_REBUILT"] = (
        blocks["STATEFP20"].str.zfill(2)
        + blocks["COUNTYFP20"].str.zfill(3)
        + blocks["TRACTCE20"].str.zfill(6)
        + blocks["BLOCKCE20"].str.zfill(4)
    )

    print("")
    print("Projecting to target CRS...")

    blocks = blocks.to_crs(target_crs)

    print("")
    print("Running QA checks...")

    geoid_length_fail = (
        blocks["GEOID20"].str.len() != 15
    )

    geoid_rebuild_fail = (
        blocks["GEOID20"]
        != blocks["GEOID20_REBUILT"]
    )

    duplicate_geoid = (
        blocks.duplicated(
            subset=["GEOID20"],
            keep=False
        )
    )

    null_geometry = (
        blocks.geometry.isna()
    )

    invalid_geometry = (
        ~blocks.geometry.is_valid
    )

    qa_summary = {
        "total_records":
            len(blocks),

        "geoid_length_failures":
            int(geoid_length_fail.sum()),

        "geoid_rebuild_mismatches":
            int(geoid_rebuild_fail.sum()),

        "duplicate_geoids":
            int(duplicate_geoid.sum()),

        "null_geometry":
            int(null_geometry.sum()),

        "invalid_geometry":
            int(invalid_geometry.sum()),
    }

    for key, value in qa_summary.items():
        print(f"{key}: {value:,}")

    qa_failures = blocks[
        geoid_length_fail
        | geoid_rebuild_fail
        | duplicate_geoid
        | null_geometry
        | invalid_geometry
    ].copy()

    qa_csv = (
        qa_root /
        "Blocks2020_Master_QA_Failures.csv"
    )

    if len(qa_failures) > 0:

        qa_failures.drop(
            columns="geometry"
        ).to_csv(
            qa_csv,
            index=False
        )

        print("")
        print(f"QA failures written to:\n{qa_csv}")

    else:

        print("")
        print("No QA failures found.")

    if qa_summary["invalid_geometry"] > 0:

        print("")
        print("Repairing invalid geometry...")

        blocks["geometry"] = (
            blocks.geometry.buffer(0)
        )

    print("")
    print("Writing GeoPackage backup...")

    gpkg_path = (
        scratch_root /
        "Blocks2020_SJTDM_Master.gpkg"
    )

    if gpkg_path.exists():
        gpkg_path.unlink()

    blocks.to_file(
        gpkg_path,
        layer=OUTPUT_LAYER,
        driver="GPKG"
    )

    print(f"Wrote:\n{gpkg_path}")

    print("")
    print("Writing File Geodatabase layer...")

    try:

        blocks.to_file(
            master_gdb,
            layer=OUTPUT_LAYER,
            driver="OpenFileGDB"
        )

        print("")
        print("File geodatabase write successful.")

    except Exception as ex:

        print("")
        print("File geodatabase write failed.")
        print(str(ex))

    print("")
    print("DONE")


if __name__ == "__main__":
    main()