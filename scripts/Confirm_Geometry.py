r"""
Confirm_Geometry_Clean.py

Purpose:
Compare original 2011 SJTDM TAZ geometry to rebuilt 2020-block-based TAZ geometry.

This script:
1. Reads the original 2011 TAZ shapefile.
2. Reads the rebuilt 2020-block-based TAZ shapefile.
3. Calculates area, perimeter, and centroid directly from geometry for both layers.
4. Uses only the TAZ ID field to match old and new TAZs.
5. Writes new QA outputs to a separate QA folder.
6. Does not modify or overwrite canonical input files.

Run from Anaconda Prompt:

conda activate tazmod_clean
cd C:\Users\Kschellinger\SJTPO_Git\TAZ_Modular
python scripts\Confirm_Geometry_Clean.py
"""

from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd


# ------------------------------------------------------------
# INPUT FILES - READ ONLY
# ------------------------------------------------------------

OLD_TAZ_PATH = Path(
    r"J:\Data Inventory\SJTDM_TAZ\SJTDM Final TAZ_Nov2011 Projected.shp"
)

NEW_TAZ_PATH = Path(
    r"J:\Data Inventory\SJTDM_TAZ\TAZ2020_Reassembled_from_Blocks_v1.shp"
)


# ------------------------------------------------------------
# OUTPUT FILES - NEW QA PRODUCTS ONLY
# ------------------------------------------------------------

OUTPUT_FOLDER = Path(
    r"J:\Data Inventory\SJTDM_TAZ\QA_Change_Review"
)

RUN_STAMP = datetime.now().strftime("%Y%m%d_%H%M")

OUTPUT_GPKG = OUTPUT_FOLDER / f"TAZ_Geometry_QA_{RUN_STAMP}.gpkg"
OUTPUT_SHP = OUTPUT_FOLDER / f"TAZ_Geometry_QA_{RUN_STAMP}.shp"
OUTPUT_CSV = OUTPUT_FOLDER / f"TAZ_Geometry_QA_{RUN_STAMP}.csv"


# ------------------------------------------------------------
# TAZ ID FIELD CANDIDATES
# ------------------------------------------------------------

OLD_ID_CANDIDATES = [
    "TAZ_ID",
    "TAZ_112011",
    "TAZ",
    "TAZID",
    "ID",
]

NEW_ID_CANDIDATES = [
    "TAZ_ID",
    "TAZ_112011",
    "TAZ",
    "TAZID",
    "ID",
]


# ------------------------------------------------------------
# FUNCTIONS
# ------------------------------------------------------------

def check_input_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def find_id_field(gdf: gpd.GeoDataFrame, candidates: list[str], layer_label: str) -> str:
    for field in candidates:
        if field in gdf.columns:
            print(f"{layer_label} TAZ ID field: {field}")
            return field

    print("")
    print(f"Could not find a TAZ ID field in {layer_label}.")
    print("Available fields:")
    for field in gdf.columns:
        print(f"  {field}")

    raise RuntimeError(f"No valid TAZ ID field found in {layer_label}.")


def normalize_taz_id(value) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    # If a numeric ID came in as 101.0, normalize it to 101.
    if text.endswith(".0"):
        text = text[:-2]

    return text


def calculate_geometry_metrics(
    gdf: gpd.GeoDataFrame,
    id_field: str,
    prefix: str,
) -> gpd.GeoDataFrame:
    """
    Keep only TAZ ID and geometry, then calculate geometry metrics.

    prefix:
      11 = original 2011 TAZ
      20 = rebuilt 2020-block TAZ
    """
    out = gdf[[id_field, "geometry"]].copy()

    out["TAZ_ID"] = out[id_field].apply(normalize_taz_id)

    out = out[out["TAZ_ID"] != ""].copy()

    area_field = f"AREA{prefix}_AC"
    perim_field = f"PER{prefix}_FT"
    cx_field = f"C{prefix}_X"
    cy_field = f"C{prefix}_Y"

    out[area_field] = out.geometry.area / 43560.0
    out[perim_field] = out.geometry.length
    out[cx_field] = out.geometry.centroid.x
    out[cy_field] = out.geometry.centroid.y

    return out[
        [
            "TAZ_ID",
            area_field,
            perim_field,
            cx_field,
            cy_field,
            "geometry",
        ]
    ].copy()


def add_change_classes(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf["AC_CLASS"] = pd.cut(
        gdf["AC_PCT"],
        bins=[-999999, -10, -5, 5, 10, 999999],
        labels=[
            "Loss gt 10 pct",
            "Loss 5 to 10 pct",
            "Stable +/- 5 pct",
            "Gain 5 to 10 pct",
            "Gain gt 10 pct",
        ],
    ).astype(str)

    gdf["CENT_CLASS"] = pd.cut(
        gdf["CENT_MI"],
        bins=[-1, 0.05, 0.10, 0.25, 0.50, 999999],
        labels=[
            "0 to 0.05 mi",
            "0.05 to 0.10 mi",
            "0.10 to 0.25 mi",
            "0.25 to 0.50 mi",
            "gt 0.50 mi",
        ],
    ).astype(str)

    gdf["REVIEW"] = "OK"

    gdf.loc[gdf["AREA11_AC"].isna(), "REVIEW"] = "NO_2011_MATCH"
    gdf.loc[gdf["AC_PCT"].abs() > 10, "REVIEW"] = "AREA_GT_10_PCT"
    gdf.loc[gdf["CENT_MI"] > 0.50, "REVIEW"] = "CENTROID_GT_0_50_MI"

    return gdf


def safe_write_outputs(gdf: gpd.GeoDataFrame) -> None:
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    protected = {
        OLD_TAZ_PATH.resolve(),
        NEW_TAZ_PATH.resolve(),
    }

    for output_path in [OUTPUT_GPKG, OUTPUT_SHP, OUTPUT_CSV]:
        if output_path.resolve() in protected:
            raise RuntimeError(f"Refusing to overwrite input file: {output_path}")

    print("")
    print(f"Writing GeoPackage: {OUTPUT_GPKG}")
    gdf.to_file(OUTPUT_GPKG, layer="TAZ_Geometry_QA", driver="GPKG")

    print(f"Writing shapefile: {OUTPUT_SHP}")
    gdf.to_file(OUTPUT_SHP)

    print(f"Writing CSV: {OUTPUT_CSV}")
    gdf.drop(columns="geometry").to_csv(OUTPUT_CSV, index=False)


def print_top_changes(qa: gpd.GeoDataFrame) -> None:
    print("")
    print("Largest absolute area percent changes")
    print(
        qa[
            [
                "TAZ_ID",
                "AREA11_AC",
                "AREA20_AC",
                "AC_DIFF",
                "AC_PCT",
                "CENT_MI",
                "REVIEW",
            ]
        ]
        .sort_values("AC_PCT", key=lambda s: s.abs(), ascending=False)
        .head(20)
        .to_string(index=False)
    )

    print("")
    print("Largest centroid shifts")
    print(
        qa[
            [
                "TAZ_ID",
                "AREA11_AC",
                "AREA20_AC",
                "AC_PCT",
                "CENT_FT",
                "CENT_MI",
                "REVIEW",
            ]
        ]
        .sort_values("CENT_MI", ascending=False)
        .head(20)
        .to_string(index=False)
    )


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main() -> None:
    print("Starting TAZ geometry QA...")

    check_input_exists(OLD_TAZ_PATH, "Original 2011 TAZ shapefile")
    check_input_exists(NEW_TAZ_PATH, "Rebuilt 2020-block TAZ shapefile")

    print("")
    print(f"Old input: {OLD_TAZ_PATH}")
    print(f"New input: {NEW_TAZ_PATH}")

    print("")
    print("Loading original 2011 TAZ layer...")
    old_taz = gpd.read_file(OLD_TAZ_PATH)

    print("Loading rebuilt 2020-block TAZ layer...")
    new_taz = gpd.read_file(NEW_TAZ_PATH)

    old_id = find_id_field(old_taz, OLD_ID_CANDIDATES, "Original 2011 TAZ")
    new_id = find_id_field(new_taz, NEW_ID_CANDIDATES, "Rebuilt 2020-block TAZ")

    print("")
    print(f"Old CRS: {old_taz.crs}")
    print(f"New CRS: {new_taz.crs}")

    if old_taz.crs != new_taz.crs:
        print("CRS mismatch found. Reprojecting old TAZ layer to match new TAZ layer.")
        old_taz = old_taz.to_crs(new_taz.crs)

    print("")
    print("Calculating geometry metrics from original 2011 TAZ geometry...")
    old_geom = calculate_geometry_metrics(old_taz, old_id, "11")

    print("Calculating geometry metrics from rebuilt 2020-block TAZ geometry...")
    new_geom = calculate_geometry_metrics(new_taz, new_id, "20")

    print("")
    print("Checking duplicate TAZ IDs...")

    old_dupes = old_geom["TAZ_ID"].duplicated().sum()
    new_dupes = new_geom["TAZ_ID"].duplicated().sum()

    print(f"Duplicate old TAZ IDs: {old_dupes}")
    print(f"Duplicate new TAZ IDs: {new_dupes}")

    if old_dupes > 0:
        print("")
        print("Duplicate old TAZ IDs found:")
        print(old_geom.loc[old_geom["TAZ_ID"].duplicated(keep=False), ["TAZ_ID"]])

    if new_dupes > 0:
        print("")
        print("Duplicate new TAZ IDs found:")
        print(new_geom.loc[new_geom["TAZ_ID"].duplicated(keep=False), ["TAZ_ID"]])

    if old_dupes > 0 or new_dupes > 0:
        raise RuntimeError("Duplicate TAZ IDs found. Resolve before QA comparison.")

    print("")
    print("Joining calculated 2011 geometry metrics to rebuilt TAZ geometry...")

    old_attrs = old_geom.drop(columns="geometry")

    qa = new_geom.merge(
        old_attrs,
        on="TAZ_ID",
        how="left",
        validate="one_to_one",
    )

    print("Calculating change metrics...")

    qa["AC_DIFF"] = qa["AREA20_AC"] - qa["AREA11_AC"]
    qa["AC_PCT"] = (qa["AC_DIFF"] / qa["AREA11_AC"]) * 100.0

    qa["PER_DIFF"] = qa["PER20_FT"] - qa["PER11_FT"]
    qa["PER_PCT"] = (qa["PER_DIFF"] / qa["PER11_FT"]) * 100.0

    qa["CENT_FT"] = (
        ((qa["C20_X"] - qa["C11_X"]) ** 2)
        + ((qa["C20_Y"] - qa["C11_Y"]) ** 2)
    ) ** 0.5

    qa["CENT_MI"] = qa["CENT_FT"] / 5280.0

    qa = add_change_classes(qa)

    print("")
    print("QA summary")
    print("--------------------------------------------------")
    print(f"Original 2011 TAZ records:       {len(old_taz)}")
    print(f"Rebuilt 2020 TAZ records:        {len(new_taz)}")
    print(f"QA output records:               {len(qa)}")
    print(f"Missing 2011 matches:            {qa['AREA11_AC'].isna().sum()}")
    print(f"Area change > 10 pct:            {(qa['AC_PCT'].abs() > 10).sum()}")
    print(f"Centroid shift > 0.50 mi:        {(qa['CENT_MI'] > 0.50).sum()}")
    print("--------------------------------------------------")

    print_top_changes(qa)

    safe_write_outputs(qa)

    print("")
    print("Done.")
    print("Outputs written to:")
    print(f"  {OUTPUT_GPKG}")
    print(f"  {OUTPUT_SHP}")
    print(f"  {OUTPUT_CSV}")


if __name__ == "__main__":
    main()