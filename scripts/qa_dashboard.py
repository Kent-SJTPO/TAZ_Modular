import os
import sys
import geopandas as gpd
import pandas as pd

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

COMPARE_GPKG = r"J:\Data Inventory\SJTDM_TAZ\TAZ2020_Reassembled_and_Comparison.gpkg"
COMPARE_LAYER = "TAZ2011_vs_TAZ2020"

OUT_DIR = r"J:\Data Inventory\SJTDM_TAZ"
OUT_CSV = os.path.join(OUT_DIR, "TAZ_Block_Assignment_QA_Dashboard.csv")
OUT_SHP = os.path.join(OUT_DIR, "TAZ_Block_Assignment_QA_Dashboard.shp")

# Review thresholds
AREA_MINOR_PCT = 10.0
AREA_MAJOR_PCT = 25.0
CENT_MINOR_FT = 500.0
CENT_MAJOR_FT = 1500.0

# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def require_exists(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing required file: {path}")


def classify_distortion(ac_pct_abs, cent_dist):
    if pd.isna(ac_pct_abs):
        return "NO_2020_MATCH"

    if ac_pct_abs >= AREA_MAJOR_PCT or cent_dist >= CENT_MAJOR_FT:
        return "HIGH_DISTORTION"

    if ac_pct_abs >= AREA_MINOR_PCT or cent_dist >= CENT_MINOR_FT:
        return "MODERATE_DISTORTION"

    return "LOW_DISTORTION"


def make_memo(row):
    taz = row["TAZ_ID"]
    old_ac = row["Old_Ac"]
    new_ac = row["New_Ac"]
    ac_chg = row["Ac_Chg"]
    ac_pct = row["Ac_Pct"]
    cent = row["Cent_Dist"]
    cov = row["Coverage"]
    flag = row["Dist_Flag"]

    if pd.isna(new_ac):
        return (
            f"TAZ {taz}: No rebuilt 2020 TAZ geometry was found. "
            f"This usually means no 2020 blocks were assigned to this legacy TAZ."
        )

    direction = "gained" if ac_chg > 0 else "lost"

    return (
        f"TAZ {taz}: Whole-block reassignment {direction} {abs(ac_chg):.2f} acres "
        f"({ac_pct:.2f}% change). Old area = {old_ac:.2f} acres; "
        f"new area = {new_ac:.2f} acres; coverage ratio = {cov:.3f}. "
        f"Centroid shifted {cent:.1f} feet. Classification: {flag}. "
        f"This is a block-assignment distortion measure, not an automatic error."
    )


def delete_shapefile_family(shp_path):
    base, _ = os.path.splitext(shp_path)
    exts = [".shp", ".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx", ".shp.xml"]
    for ext in exts:
        p = base + ext
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():
    print("TAZ block-assignment QA dashboard starting...")
    print("Python:", sys.executable)

    require_exists(COMPARE_GPKG)

    print("Reading comparison layer...")
    qa = gpd.read_file(COMPARE_GPKG, layer=COMPARE_LAYER)

    required = ["TAZ_ID", "Old_Ac", "New_Ac", "Ac_Chg", "Ac_Pct", "Cent_Dist"]
    missing = [f for f in required if f not in qa.columns]

    if missing:
        raise RuntimeError(f"Missing required fields: {missing}")

    print(f"Records loaded: {len(qa):,}")

    qa["Ac_Pct_Abs"] = qa["Ac_Pct"].abs()
    qa["Coverage"] = qa["New_Ac"] / qa["Old_Ac"]

    qa["Dist_Flag"] = qa.apply(
        lambda r: classify_distortion(r["Ac_Pct_Abs"], r["Cent_Dist"]),
        axis=1
    )

    qa["Review_Pri"] = (
        qa["Ac_Pct_Abs"].fillna(9999) * 10.0
        + qa["Cent_Dist"].fillna(9999) / 100.0
    )

    qa["Dist_Memo"] = qa.apply(make_memo, axis=1)

    qa = qa.sort_values("Review_Pri", ascending=False)

    keep_fields = [
        "TAZ_ID",
        "Old_Ac",
        "New_Ac",
        "Ac_Chg",
        "Ac_Pct",
        "Ac_Pct_Abs",
        "Coverage",
        "Cent_Dist",
        "Dist_Flag",
        "Review_Pri",
        "Dist_Memo",
        "geometry"
    ]

    qa_out = qa[keep_fields].copy()

    print("Writing CSV dashboard...")
    qa_out.drop(columns="geometry").to_csv(OUT_CSV, index=False)

    print("Writing shapefile dashboard...")
    delete_shapefile_family(OUT_SHP)

    shp_out = qa_out.copy()

    # Shapefile field names are limited, so keep the memo in CSV.
    # The shapefile gets short fields for mapping and sorting.
    shp_out = shp_out[
        [
            "TAZ_ID",
            "Old_Ac",
            "New_Ac",
            "Ac_Chg",
            "Ac_Pct",
            "Coverage",
            "Cent_Dist",
            "Dist_Flag",
            "Review_Pri",
            "geometry"
        ]
    ].copy()

    shp_out.to_file(OUT_SHP)

    print("")
    print("Done.")
    print("CSV:", OUT_CSV)
    print("SHP:", OUT_SHP)
    print("")
    print("Distortion summary:")
    print(qa_out["Dist_Flag"].value_counts(dropna=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())