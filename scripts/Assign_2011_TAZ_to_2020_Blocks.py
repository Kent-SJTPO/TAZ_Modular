# Assign_2011_TAZ_to_2020_Blocks.py

from pathlib import Path
import geopandas as gpd
import pandas as pd
import pyodbc


SETTINGS_DB = (
    r"H:\Planning\SJTDM\FY 2025 Recalibration"
    r"\Demographics\CensusBlocks.accdb"
)

BLOCKS_LAYER = "Blocks2020_SJTDM_Master"
TAZ_LAYER = "SJTDM_Final_TAZ_Nov2011"

OUTPUT_LAYER = "TAZ2011_Assigned_2020_Blocks"


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


def pick_taz_id_field(taz):
    candidates = [
        "TAZ_112011",
        "TAZ2011",
        "TAZ",
        "ID",
        "OBJECTID",
        "FID",
    ]

    for field in candidates:
        if field in taz.columns:
            return field

    raise ValueError("Could not identify a TAZ ID field.")


def main():
    print("")
    print("Reading settings...")

    settings = get_settings(SETTINGS_DB)

    gis_root = Path(settings["GISRoot"])
    master_gdb = Path(settings["MasterGDB"])
    target_crs = settings["TargetCRS"]

    scratch_root = gis_root / "Scratch"
    qa_root = gis_root / "QA"

    scratch_root.mkdir(parents=True, exist_ok=True)
    qa_root.mkdir(parents=True, exist_ok=True)

    print(f"GIS root:   {gis_root}")
    print(f"Master GDB: {master_gdb}")
    print(f"Target CRS: {target_crs}")
    print("")

    print("Reading blocks...")

    blocks = gpd.read_file(
        master_gdb,
        layer=BLOCKS_LAYER
    )

    print(f"Blocks: {len(blocks):,}")

    print("Reading TAZs...")

    taz = gpd.read_file(
        master_gdb,
        layer=TAZ_LAYER
    )

    print(f"TAZ records: {len(taz):,}")

    print("")
    print("Projecting layers...")

    blocks = blocks.to_crs(target_crs)
    taz = taz.to_crs(target_crs)

    taz_id_field = pick_taz_id_field(taz)

    print(f"Using TAZ ID field: {taz_id_field}")

    taz_keep = taz[[taz_id_field, "geometry"]].copy()
    taz_keep = taz_keep.rename(columns={taz_id_field: "TAZ_112011"})

    print("")
    print("Calculating original block area...")

    blocks["BLOCK_AREA_FT2"] = blocks.geometry.area

    print("Assigning blocks fully contained in TAZs...")

    contained = gpd.sjoin(
        blocks,
        taz_keep,
        how="left",
        predicate="within"
    )

    contained["ASSIGN_METHOD"] = None
    contained.loc[
        contained["TAZ_112011"].notna(),
        "ASSIGN_METHOD"
    ] = "CONTAINED"

    assigned = contained[
        contained["TAZ_112011"].notna()
    ].copy()

    unassigned = contained[
        contained["TAZ_112011"].isna()
    ].copy()

    unassigned = unassigned.drop(
        columns=[
            col for col in unassigned.columns
            if col.startswith("index_")
        ],
        errors="ignore"
    )

    print(f"Contained assignments: {len(assigned):,}")
    print(f"Unassigned after within test: {len(unassigned):,}")

    if len(unassigned) > 0:
        print("")
        print("Assigning remaining blocks by dominant area overlap...")

        intersections = gpd.overlay(
            unassigned,
            taz_keep,
            how="intersection",
            keep_geom_type=True
        )

        intersections["OVERLAP_AREA_FT2"] = intersections.geometry.area

        intersections = intersections.sort_values(
            ["GEOID20", "OVERLAP_AREA_FT2"],
            ascending=[True, False]
        )

        dominant = intersections.drop_duplicates(
            subset=["GEOID20"],
            keep="first"
        ).copy()

        dominant["ASSIGN_METHOD"] = "DOMINANT_AREA"

        dominant = dominant.drop(
            columns=[
                col for col in dominant.columns
                if col.startswith("index_")
            ],
            errors="ignore"
        )

        assigned = pd.concat(
            [assigned, dominant],
            ignore_index=True
        )

    assigned = gpd.GeoDataFrame(
        assigned,
        geometry="geometry",
        crs=blocks.crs
    )

    assigned = assigned.drop(
        columns=[
            col for col in assigned.columns
            if col.startswith("index_")
        ],
        errors="ignore"
    )

    assigned["TAZ_112011"] = assigned["TAZ_112011"].astype(str)

    print("")
    print("Running assignment QA...")

    total_blocks = len(blocks)
    total_assigned = len(assigned)
    unique_assigned = assigned["GEOID20"].nunique()
    duplicate_geoids = assigned.duplicated(
        subset=["GEOID20"],
        keep=False
    ).sum()

    print(f"Input blocks:        {total_blocks:,}")
    print(f"Assigned records:    {total_assigned:,}")
    print(f"Unique GEOID20:      {unique_assigned:,}")
    print(f"Duplicate GEOID20:   {duplicate_geoids:,}")

    missing_geoids = set(blocks["GEOID20"]) - set(assigned["GEOID20"])

    print(f"Missing assignments: {len(missing_geoids):,}")

    if len(missing_geoids) > 0:
        missing = blocks[
            blocks["GEOID20"].isin(missing_geoids)
        ].copy()

        missing_csv = qa_root / "TAZ2011_Assigned_2020_Blocks_Missing.csv"

        missing.drop(columns="geometry").to_csv(
            missing_csv,
            index=False
        )

        print(f"Missing assignment CSV written: {missing_csv}")

    if duplicate_geoids > 0:
        dupes = assigned[
            assigned.duplicated(
                subset=["GEOID20"],
                keep=False
            )
        ].copy()

        dupes_csv = qa_root / "TAZ2011_Assigned_2020_Blocks_Duplicates.csv"

        dupes.drop(columns="geometry").to_csv(
            dupes_csv,
            index=False
        )

        print(f"Duplicate assignment CSV written: {dupes_csv}")

    print("")
    print("Writing GeoPackage output...")

    gpkg_path = scratch_root / "TAZ2011_Assigned_2020_Blocks.gpkg"

    if gpkg_path.exists():
        gpkg_path.unlink()

    assigned.to_file(
        gpkg_path,
        layer=OUTPUT_LAYER,
        driver="GPKG"
    )

    print(f"Wrote GeoPackage: {gpkg_path}")

    print("")
    print("Attempting File Geodatabase write...")

    try:
        assigned.to_file(
            master_gdb,
            layer=OUTPUT_LAYER,
            driver="OpenFileGDB"
        )

        print("File geodatabase write successful.")

    except Exception as ex:
        print("File geodatabase write failed.")
        print(str(ex))
        print("")
        print("Use the GeoPackage output and import it into ArcGIS Pro:")
        print(gpkg_path)

    print("")
    print("DONE")


if __name__ == "__main__":
    main()