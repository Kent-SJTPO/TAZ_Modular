"""
Count_2020_Blocks_Entirely_Within_TAZ.py

Count complete 2020 Census Blocks that are entirely covered by exactly one
legacy SJTDM TAZ_112011 polygon. A coincident block/TAZ boundary is accepted.

This is a diagnostic script only. It does not assign crossing blocks, dissolve
TAZs, or modify either canonical input layer.
"""

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

OUTPUT_GPKG_NAME = "Blocks2020_Within_TAZ2011_Diagnostic.gpkg"
OUTPUT_SUMMARY_CSV_NAME = "Blocks2020_Within_TAZ2011_Summary.csv"

WITHIN_LAYER = "BLOCKS_ENTIRELY_WITHIN_TAZ"
CROSSING_LAYER = "BLOCKS_NOT_ENTIRELY_WITHIN"
OUTSIDE_LAYER = "BLOCKS_NO_TAZ_INTERSECTION"
AMBIGUOUS_LAYER = "BLOCKS_COVERED_BY_MULTIPLE_TAZ"


def get_settings(accdb_path):
    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={accdb_path};"
    )

    conn = pyodbc.connect(conn_str)
    rows = conn.execute(
        """
        SELECT SettingName, SettingValue
        FROM tblSystemSettings
        WHERE IsActive = True
        """
    ).fetchall()
    conn.close()

    return {row.SettingName: row.SettingValue for row in rows}


def pick_taz_id_field(taz):
    candidates = [
        "TAZ_112011",
        "TAZ2011",
        "TAZ_ID",
        "TAZ",
        "ID",
        "OBJECTID",
        "FID",
    ]

    for field in candidates:
        if field in taz.columns:
            return field

    raise ValueError(
        "Could not identify a TAZ ID field. Available fields: "
        + ", ".join(taz.columns)
    )


def normalize_identifier(series):
    out = series.astype("string").str.strip()
    return out.str.replace(r"\.0$", "", regex=True)


def remove_join_fields(frame):
    return frame.drop(
        columns=[c for c in frame.columns if c.startswith("index_")],
        errors="ignore",
    )


def write_gdb_layer(frame, master_gdb, layer_name):
    if frame.empty:
        print(f"Skipping empty geodatabase layer: {layer_name}")
        return

    try:
        frame.to_file(
            master_gdb,
            layer=layer_name,
            driver="OpenFileGDB",
            promote_to_multi=True,
        )
        print(f"File geodatabase write successful: {layer_name}")
    except Exception as ex:
        print(f"File geodatabase write failed for {layer_name}.")
        print(str(ex))


def main():
    print("")
    print("2020 Blocks entirely within 2011 TAZ boundaries")
    print("Strict test: complete block covered by exactly one TAZ.")

    settings = get_settings(SETTINGS_DB)
    gis_root = Path(settings["GISRoot"])
    master_gdb = Path(settings["MasterGDB"])
    target_crs = settings["TargetCRS"]

    scratch_root = gis_root / "Scratch"
    qa_root = gis_root / "QA"
    scratch_root.mkdir(parents=True, exist_ok=True)
    qa_root.mkdir(parents=True, exist_ok=True)

    output_gpkg = scratch_root / OUTPUT_GPKG_NAME
    output_summary_csv = qa_root / OUTPUT_SUMMARY_CSV_NAME

    if not master_gdb.exists():
        raise FileNotFoundError(f"Master geodatabase not found: {master_gdb}")

    print("")
    print("Reading 2020 Census Blocks...")
    blocks = gpd.read_file(master_gdb, layer=BLOCKS_LAYER)

    print("Reading legacy 2011 TAZs...")
    taz = gpd.read_file(master_gdb, layer=TAZ_LAYER)

    if "GEOID20" not in blocks.columns:
        raise ValueError("The block layer does not contain GEOID20.")

    blocks = blocks.to_crs(target_crs)
    taz = taz.to_crs(target_crs)

    blocks = blocks[blocks.geometry.notna() & ~blocks.geometry.is_empty].copy()
    taz = taz[taz.geometry.notna() & ~taz.geometry.is_empty].copy()

    taz_id_field = pick_taz_id_field(taz)
    blocks["GEOID20"] = normalize_identifier(blocks["GEOID20"])
    taz["TAZ_112011"] = normalize_identifier(taz[taz_id_field])

    if blocks["GEOID20"].isna().any() or blocks["GEOID20"].duplicated().any():
        raise RuntimeError("GEOID20 must be populated and unique.")

    if taz["TAZ_112011"].isna().any() or taz["TAZ_112011"].duplicated().any():
        raise RuntimeError("TAZ_112011 must be populated and unique.")

    print(f"Input blocks: {len(blocks):,}")
    print(f"Input TAZs:   {len(taz):,}")
    print(f"Using TAZ ID field: {taz_id_field}")

    block_geometry = blocks.copy()
    taz_join = taz[["TAZ_112011", "geometry"]].copy()

    print("")
    print("Testing whether each complete block is covered by a TAZ...")
    covered_join = gpd.sjoin(
        block_geometry,
        taz_join,
        how="left",
        predicate="covered_by",
    )

    covered_matches = covered_join[covered_join["TAZ_112011"].notna()].copy()
    covered_counts = (
        covered_matches.groupby("GEOID20")["TAZ_112011"]
        .nunique()
        .rename("COVERING_TAZ_COUNT")
    )

    unique_covered = covered_matches[
        covered_matches["GEOID20"].map(covered_counts) == 1
    ].copy()
    unique_covered = unique_covered.drop_duplicates("GEOID20")
    unique_covered = remove_join_fields(unique_covered)
    unique_covered["BLOCK_STATUS"] = "ENTIRELY_WITHIN_ONE_TAZ"

    ambiguous_ids = set(covered_counts[covered_counts > 1].index)
    ambiguous = blocks[blocks["GEOID20"].isin(ambiguous_ids)].copy()
    ambiguous["COVERING_TAZ_COUNT"] = ambiguous["GEOID20"].map(covered_counts)
    ambiguous["BLOCK_STATUS"] = "COVERED_BY_MULTIPLE_TAZ"

    classified_ids = set(unique_covered["GEOID20"]) | ambiguous_ids
    not_covered = blocks[~blocks["GEOID20"].isin(classified_ids)].copy()

    print("Separating boundary-crossing blocks from blocks outside all TAZs...")
    if not_covered.empty:
        crossing = not_covered.copy()
        outside = not_covered.copy()
    else:
        intersect_join = gpd.sjoin(
            not_covered,
            taz_join,
            how="left",
            predicate="intersects",
        )
        intersecting_ids = set(
            intersect_join.loc[
                intersect_join["TAZ_112011"].notna(),
                "GEOID20",
            ]
        )

        crossing = not_covered[
            not_covered["GEOID20"].isin(intersecting_ids)
        ].copy()
        crossing["BLOCK_STATUS"] = "NOT_ENTIRELY_WITHIN_TAZ"

        outside = not_covered[
            ~not_covered["GEOID20"].isin(intersecting_ids)
        ].copy()
        outside["BLOCK_STATUS"] = "NO_TAZ_INTERSECTION"

    total = len(blocks)
    entirely_within_count = len(unique_covered)
    crossing_count = len(crossing)
    outside_count = len(outside)
    ambiguous_count = len(ambiguous)

    summary_rows = [
        ("TOTAL_2020_BLOCKS", total),
        ("ENTIRELY_WITHIN_ONE_TAZ", entirely_within_count),
        ("NOT_ENTIRELY_WITHIN_TAZ", crossing_count),
        ("NO_TAZ_INTERSECTION", outside_count),
        ("COVERED_BY_MULTIPLE_TAZ", ambiguous_count),
    ]

    summary = pd.DataFrame(summary_rows, columns=["BLOCK_CATEGORY", "BLOCK_COUNT"])
    summary["PERCENT_OF_TOTAL"] = summary["BLOCK_COUNT"] / total * 100.0

    print("")
    print("Block containment results")
    print("--------------------------------------------------")
    print(f"Total 2020 Blocks:              {total:,}")
    print(
        f"Entirely within exactly 1 TAZ:  {entirely_within_count:,} "
        f"({entirely_within_count / total * 100.0:.2f}%)"
    )
    print(
        f"Not entirely within a TAZ:      {crossing_count:,} "
        f"({crossing_count / total * 100.0:.2f}%)"
    )
    print(
        f"No TAZ intersection:            {outside_count:,} "
        f"({outside_count / total * 100.0:.2f}%)"
    )
    print(
        f"Covered by multiple TAZs:        {ambiguous_count:,} "
        f"({ambiguous_count / total * 100.0:.2f}%)"
    )
    print("--------------------------------------------------")

    if output_gpkg.exists():
        output_gpkg.unlink()

    print("")
    print(f"Writing GeoPackage: {output_gpkg}")
    if not unique_covered.empty:
        unique_covered.to_file(output_gpkg, layer=WITHIN_LAYER, driver="GPKG")
    if not crossing.empty:
        crossing.to_file(output_gpkg, layer=CROSSING_LAYER, driver="GPKG")
    if not outside.empty:
        outside.to_file(output_gpkg, layer=OUTSIDE_LAYER, driver="GPKG")
    if not ambiguous.empty:
        ambiguous.to_file(output_gpkg, layer=AMBIGUOUS_LAYER, driver="GPKG")

    summary.to_csv(output_summary_csv, index=False)
    print(f"Writing summary CSV: {output_summary_csv}")

    print("")
    print("Attempting File Geodatabase writes...")
    write_gdb_layer(unique_covered, master_gdb, WITHIN_LAYER)
    write_gdb_layer(crossing, master_gdb, CROSSING_LAYER)
    write_gdb_layer(outside, master_gdb, OUTSIDE_LAYER)
    write_gdb_layer(ambiguous, master_gdb, AMBIGUOUS_LAYER)

    print("")
    print("DONE")


if __name__ == "__main__":
    main()
