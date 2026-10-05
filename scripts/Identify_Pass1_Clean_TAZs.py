"""
Identify_Pass1_Clean_TAZs.py

Purpose
-------
Identify legacy 2011 SJTDM TAZs that can be reconstructed entirely from
complete 2020 Census Blocks without making any judgment about blocks that
cross a TAZ boundary.

This is Pass 1 only. It deliberately does NOT use dominant-area assignment.
Accepted TAZs and their blocks are locked; every other TAZ is written to an
exception layer for later processing.
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyodbc
from shapely.ops import unary_union


SETTINGS_DB = (
    r"H:\Planning\SJTDM\FY 2025 Recalibration"
    r"\Demographics\CensusBlocks.accdb"
)

BLOCKS_LAYER = "Blocks2020_SJTDM_Master"
TAZ_LAYER = "SJTDM_Final_TAZ_Nov2011"

OUTPUT_GPKG_NAME = "TAZ2020_Pass1_Clean.gpkg"
OUTPUT_QA_CSV_NAME = "TAZ2020_Pass1_QA.csv"

ACCEPTED_TAZ_LAYER = "TAZ_PASS1_ACCEPTED"
LOCKED_BLOCK_LAYER = "BLOCKS_PASS1_LOCKED"
EXCEPTION_TAZ_LAYER = "TAZ_PASS1_EXCEPTIONS"

# A block is accepted only when both the area-ratio test and the maximum
# outward-distance test are satisfied.
WHOLE_BLOCK_MIN_RATIO = 0.98
MAX_BLOCK_OUTSIDE_DISTANCE_FT = 100.0

# Ignore intersection fragments smaller than this area. TargetCRS is expected
# to use US survey feet, so this value is in square feet.
MIN_INTERSECTION_AREA_FT2 = 10.0

# The union of the complete blocks must reproduce the legacy TAZ within this
# proportional symmetric-difference tolerance.
MAX_TAZ_SYMDIFF_RATIO = 0.02


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
    out = out.str.replace(r"\.0$", "", regex=True)
    return out


def drop_spatial_join_fields(frame):
    return frame.drop(
        columns=[c for c in frame.columns if c.startswith("index_")],
        errors="ignore",
    )


def polygonal_only(geometry):
    """Return only polygonal parts so OpenFileGDB never receives a collection."""
    if geometry is None or geometry.is_empty:
        return geometry

    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry

    polygon_parts = []
    for part in getattr(geometry, "geoms", []):
        cleaned = polygonal_only(part)
        if cleaned is not None and not cleaned.is_empty:
            polygon_parts.append(cleaned)

    if not polygon_parts:
        return None

    return unary_union(polygon_parts)


def write_gdb_layer(frame, master_gdb, layer_name):
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
    print("TAZ 2020 Pass 1: clean whole-block reconstruction")
    print("No dominant-area assignments will be made.")

    settings = get_settings(SETTINGS_DB)
    gis_root = Path(settings["GISRoot"])
    master_gdb = Path(settings["MasterGDB"])
    target_crs = settings["TargetCRS"]

    scratch_root = gis_root / "Scratch"
    qa_root = gis_root / "QA"
    scratch_root.mkdir(parents=True, exist_ok=True)
    qa_root.mkdir(parents=True, exist_ok=True)

    output_gpkg = scratch_root / OUTPUT_GPKG_NAME
    output_qa_csv = qa_root / OUTPUT_QA_CSV_NAME

    if not master_gdb.exists():
        raise FileNotFoundError(f"Master geodatabase not found: {master_gdb}")

    print("")
    print("Reading 2020 Census Blocks...")
    blocks = gpd.read_file(master_gdb, layer=BLOCKS_LAYER)

    print("Reading legacy 2011 TAZs...")
    taz = gpd.read_file(master_gdb, layer=TAZ_LAYER)

    if "GEOID20" not in blocks.columns:
        raise ValueError("The block layer does not contain GEOID20.")

    print(f"Input blocks: {len(blocks):,}")
    print(f"Input TAZs:   {len(taz):,}")

    blocks = blocks.to_crs(target_crs)
    taz = taz.to_crs(target_crs)

    blocks = blocks[blocks.geometry.notna()].copy()
    taz = taz[taz.geometry.notna()].copy()
    blocks["geometry"] = blocks.geometry.buffer(0)
    taz["geometry"] = taz.geometry.buffer(0)

    taz_id_field = pick_taz_id_field(taz)
    print(f"Using TAZ ID field: {taz_id_field}")

    blocks["GEOID20"] = normalize_identifier(blocks["GEOID20"])
    taz["TAZ_ID"] = normalize_identifier(taz[taz_id_field])

    if blocks["GEOID20"].isna().any() or blocks["GEOID20"].duplicated().any():
        raise RuntimeError("GEOID20 must be populated and unique before Pass 1.")

    if taz["TAZ_ID"].isna().any() or taz["TAZ_ID"].duplicated().any():
        raise RuntimeError("TAZ identifiers must be populated and unique before Pass 1.")

    blocks["BLOCK_AREA_FT2"] = blocks.geometry.area
    taz["TAZ_AREA_FT2"] = taz.geometry.area

    blocks_overlay = blocks[["GEOID20", "BLOCK_AREA_FT2", "geometry"]].copy()
    taz_overlay = taz[["TAZ_ID", "geometry"]].copy()

    print("")
    print("Intersecting blocks and TAZs for classification only...")
    intersections = gpd.overlay(
        blocks_overlay,
        taz_overlay,
        how="intersection",
        keep_geom_type=True,
    )

    intersections["INTERSECT_FT2"] = intersections.geometry.area
    intersections = intersections[
        intersections["INTERSECT_FT2"] >= MIN_INTERSECTION_AREA_FT2
    ].copy()

    intersections["BLOCK_RATIO"] = (
        intersections["INTERSECT_FT2"] / intersections["BLOCK_AREA_FT2"]
    )

    block_summary = (
        intersections.groupby("GEOID20", as_index=False)
        .agg(
            TAZ_HIT_COUNT=("TAZ_ID", "nunique"),
            MAX_BLOCK_RATIO=("BLOCK_RATIO", "max"),
        )
    )

    winner_index = intersections.groupby("GEOID20")["INTERSECT_FT2"].idxmax()
    winners = intersections.loc[
        winner_index,
        ["GEOID20", "TAZ_ID", "BLOCK_RATIO"],
    ].copy()
    winners = winners.rename(columns={"BLOCK_RATIO": "WIN_BLOCK_RATIO"})

    block_summary = block_summary.merge(
        winners,
        on="GEOID20",
        how="left",
        validate="one_to_one",
    )

    # The buffered coverage test means every point in the complete block must
    # fall within the winning TAZ or within 100 feet outside its boundary.
    # Combined with the 98-percent overlap requirement, this limits both the
    # depth and the area of an accepted boundary discrepancy.
    block_geometry_by_id = dict(zip(blocks["GEOID20"], blocks.geometry))
    taz_geometry_by_id = dict(zip(taz["TAZ_ID"], taz.geometry))

    def passes_distance_test(row):
        block_geometry = block_geometry_by_id.get(row["GEOID20"])
        winning_taz_geometry = taz_geometry_by_id.get(row["TAZ_ID"])

        if block_geometry is None or winning_taz_geometry is None:
            return False

        allowed_area = winning_taz_geometry.buffer(
            MAX_BLOCK_OUTSIDE_DISTANCE_FT
        )
        return block_geometry.covered_by(allowed_area)

    block_summary["WITHIN_100_FT"] = block_summary.apply(
        passes_distance_test,
        axis=1,
    )
    block_summary["IS_WHOLE_BLOCK"] = (
        (block_summary["MAX_BLOCK_RATIO"] >= WHOLE_BLOCK_MIN_RATIO)
        & block_summary["WITHIN_100_FT"]
    )

    # Join the classification back to the ORIGINAL complete block geometry.
    # Intersection geometry is never used as an output block geometry.
    classified_blocks = blocks.merge(
        block_summary,
        on="GEOID20",
        how="left",
        validate="one_to_one",
    )
    classified_blocks = gpd.GeoDataFrame(
        classified_blocks,
        geometry="geometry",
        crs=blocks.crs,
    )

    whole_blocks = classified_blocks[
        classified_blocks["IS_WHOLE_BLOCK"].fillna(False)
    ].copy()

    print(f"Whole blocks provisionally assigned: {len(whole_blocks):,}")

    print("Assembling provisional TAZs from complete blocks...")
    if len(whole_blocks) > 0:
        assembled = whole_blocks.dissolve(by="TAZ_ID", as_index=False)
        assembled["geometry"] = assembled.geometry.buffer(0)
        assembled = assembled[["TAZ_ID", "geometry"]].copy()
    else:
        assembled = gpd.GeoDataFrame(
            {"TAZ_ID": pd.Series(dtype="string")},
            geometry=gpd.GeoSeries([], crs=blocks.crs),
            crs=blocks.crs,
        )

    # Count every meaningful block intersection for each TAZ, including
    # crossing blocks that prevent automatic acceptance.
    taz_hit_stats = (
        intersections.groupby("TAZ_ID", as_index=False)
        .agg(INTERSECT_BLOCKS=("GEOID20", "nunique"))
    )

    # Count unique crossing blocks rather than intersection rows.
    crossing_ids = set(
        block_summary.loc[~block_summary["IS_WHOLE_BLOCK"], "GEOID20"]
    )
    crossing_by_taz = (
        intersections[intersections["GEOID20"].isin(crossing_ids)]
        .groupby("TAZ_ID")["GEOID20"]
        .nunique()
        .rename("CROSSING_BLOCKS")
        .reset_index()
    )
    taz_hit_stats = taz_hit_stats.merge(
        crossing_by_taz,
        on="TAZ_ID",
        how="left",
    )
    taz_hit_stats["CROSSING_BLOCKS"] = (
        taz_hit_stats["CROSSING_BLOCKS"].fillna(0).astype(int)
    )

    qa = taz[["TAZ_ID", "TAZ_AREA_FT2", "geometry"]].copy()
    qa = qa.merge(taz_hit_stats, on="TAZ_ID", how="left")
    assembled_geometry = dict(zip(assembled["TAZ_ID"], assembled.geometry))
    qa["ASSEMBLED_GEOMETRY"] = qa["TAZ_ID"].map(assembled_geometry)

    qa["INTERSECT_BLOCKS"] = qa["INTERSECT_BLOCKS"].fillna(0).astype(int)
    qa["CROSSING_BLOCKS"] = qa["CROSSING_BLOCKS"].fillna(0).astype(int)

    def calculate_difference(row):
        new_geometry = row["ASSEMBLED_GEOMETRY"]
        if new_geometry is None or pd.isna(new_geometry):
            return pd.Series(
                {
                    "ASSEMBLED_AREA_FT2": pd.NA,
                    "SYMDIFF_FT2": pd.NA,
                    "SYMDIFF_RATIO": pd.NA,
                }
            )

        assembled_area = new_geometry.area
        symdiff_area = row["geometry"].symmetric_difference(new_geometry).area
        ratio = symdiff_area / row["TAZ_AREA_FT2"] if row["TAZ_AREA_FT2"] else pd.NA
        return pd.Series(
            {
                "ASSEMBLED_AREA_FT2": assembled_area,
                "SYMDIFF_FT2": symdiff_area,
                "SYMDIFF_RATIO": ratio,
            }
        )

    difference_metrics = qa.apply(calculate_difference, axis=1)
    qa = pd.concat([qa, difference_metrics], axis=1)

    qa["PASS1_ACCEPT"] = (
        (qa["INTERSECT_BLOCKS"] > 0)
        & (qa["CROSSING_BLOCKS"] == 0)
        & (qa["SYMDIFF_RATIO"].notna())
        & (qa["SYMDIFF_RATIO"] <= MAX_TAZ_SYMDIFF_RATIO)
    )

    def make_reason(row):
        if row["PASS1_ACCEPT"]:
            return "ACCEPTED_COMPLETE_2020_BLOCKS"
        if row["INTERSECT_BLOCKS"] == 0:
            return "NO_2020_BLOCK_INTERSECTION"
        if row["CROSSING_BLOCKS"] > 0:
            return "BOUNDARY_CROSSING_BLOCKS"
        if pd.isna(row["SYMDIFF_RATIO"]):
            return "NO_REASSEMBLED_GEOMETRY"
        return "TAZ_COVERAGE_DIFFERENCE"

    qa["PASS1_REASON"] = qa.apply(make_reason, axis=1)

    accepted_ids = set(qa.loc[qa["PASS1_ACCEPT"], "TAZ_ID"])

    accepted_taz = assembled[assembled["TAZ_ID"].isin(accepted_ids)].copy()
    accepted_attrs = qa.drop(columns=["geometry", "ASSEMBLED_GEOMETRY"])
    accepted_taz = accepted_taz.merge(
        accepted_attrs,
        on="TAZ_ID",
        how="left",
        validate="one_to_one",
    )
    accepted_taz = gpd.GeoDataFrame(
        accepted_taz,
        geometry="geometry",
        crs=blocks.crs,
    )

    locked_blocks = whole_blocks[whole_blocks["TAZ_ID"].isin(accepted_ids)].copy()
    locked_blocks["ASSIGN_METHOD"] = "PASS1_LOCKED"

    exception_taz = qa[~qa["PASS1_ACCEPT"]].drop(
        columns="ASSEMBLED_GEOMETRY"
    ).copy()
    exception_taz["geometry"] = exception_taz.geometry.apply(polygonal_only)
    exception_taz = exception_taz[
        exception_taz.geometry.notna() & ~exception_taz.geometry.is_empty
    ].copy()
    exception_taz = gpd.GeoDataFrame(
        exception_taz,
        geometry="geometry",
        crs=taz.crs,
    )

    print("")
    print("Pass 1 results")
    print("--------------------------------------------------")
    print(f"Accepted TAZs:     {len(accepted_taz):,}")
    print(f"Exception TAZs:    {len(exception_taz):,}")
    print(f"Locked blocks:     {len(locked_blocks):,}")
    print(f"Unresolved blocks: {len(blocks) - len(locked_blocks):,}")
    print("--------------------------------------------------")
    print(qa["PASS1_REASON"].value_counts(dropna=False).to_string())

    if output_gpkg.exists():
        output_gpkg.unlink()

    print("")
    print(f"Writing GeoPackage: {output_gpkg}")
    accepted_taz.to_file(
        output_gpkg,
        layer=ACCEPTED_TAZ_LAYER,
        driver="GPKG",
    )
    locked_blocks.to_file(
        output_gpkg,
        layer=LOCKED_BLOCK_LAYER,
        driver="GPKG",
    )
    exception_taz.to_file(
        output_gpkg,
        layer=EXCEPTION_TAZ_LAYER,
        driver="GPKG",
    )

    qa.drop(columns=["geometry", "ASSEMBLED_GEOMETRY"]).to_csv(
        output_qa_csv,
        index=False,
    )
    print(f"Writing QA table: {output_qa_csv}")

    print("")
    print("Attempting File Geodatabase writes...")
    write_gdb_layer(accepted_taz, master_gdb, ACCEPTED_TAZ_LAYER)
    write_gdb_layer(locked_blocks, master_gdb, LOCKED_BLOCK_LAYER)
    write_gdb_layer(exception_taz, master_gdb, EXCEPTION_TAZ_LAYER)

    print("")
    print("DONE")


if __name__ == "__main__":
    main()
