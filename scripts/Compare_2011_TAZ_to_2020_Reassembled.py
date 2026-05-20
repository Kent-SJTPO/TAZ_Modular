from pathlib import Path
import geopandas as gpd
import pandas as pd


# ------------------------------------------------------------
# FILE PATHS
# ------------------------------------------------------------

REPO_ROOT = Path(r"C:\Users\Kschellinger\SJTPO_Git\TAZ_Modular")

OLD_2011_TAZ_PATH = Path(
    r"J:\Data Inventory\SJTDM_TAZ\SJTDM Final TAZ_Nov2011.shp"
)

ASSIGNED_2020_BLOCKS_PATH = Path(
    r"J:\Data Inventory\SJTDM_TAZ\TAZ2011_Assigned_2020_Blocks.shp"
)

OUTPUT_FOLDER = REPO_ROOT / "output" / "comparison"
OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

OUTPUT_2020_REASSEMBLED_GPKG = OUTPUT_FOLDER / "TAZ2020_Reassembled_from_Blocks_v1.gpkg"
OUTPUT_COMPARISON_GPKG = OUTPUT_FOLDER / "TAZ_2011_vs_2020_Comparison.gpkg"
OUTPUT_COMPARISON_CSV = OUTPUT_FOLDER / "TAZ_2011_vs_2020_Comparison.csv"

PROJECTED_CRS = "EPSG:6539"


# ------------------------------------------------------------
# FIELD SETTINGS
# ------------------------------------------------------------

OLD_TAZ_ID_FIELD_CANDIDATES = ["TAZ_ID", "TAZID", "TAZ", "ID"]

BLOCK_TAZ_ID_FIELD_CANDIDATES = [
    "TAZ_112011", "TAZ_ID", "TAZID", "TAZ",
    "TAZ2011", "TAZ_2011", "ASSIGN_TAZ"
]


# ------------------------------------------------------------
# QA THRESHOLDS
# ------------------------------------------------------------

AREA_OK_PCT = 1.0
AREA_MINOR_PCT = 5.0
AREA_MOD_PCT = 10.0

CENTROID_OK_FT = 50.0
CENTROID_MINOR_FT = 250.0
CENTROID_MOD_FT = 1000.0


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def find_field(gdf, candidates):
    cols = {c.upper(): c for c in gdf.columns}
    for c in candidates:
        if c.upper() in cols:
            return cols[c.upper()]
    raise ValueError(f"Field not found. Available: {list(gdf.columns)}")


def prepare(gdf):
    if gdf.crs is None:
        raise ValueError("Missing CRS")
    return gdf.to_crs(PROJECTED_CRS)


def classify_area(p):
    if pd.isna(p): return "NO_MATCH"
    if p < AREA_OK_PCT: return "OK"
    if p < AREA_MINOR_PCT: return "MINOR"
    if p < AREA_MOD_PCT: return "MOD"
    return "MAJOR"


def classify_cent(d):
    if pd.isna(d): return "NO_MATCH"
    if d < CENTROID_OK_FT: return "OK"
    if d < CENTROID_MINOR_FT: return "MINOR"
    if d < CENTROID_MOD_FT: return "MOD"
    return "MAJOR"


def worst_flag(a, c):
    rank = {"OK":0,"MINOR":1,"MOD":2,"MAJOR":3,"NO_MATCH":4}
    return max([a,c], key=lambda x: rank.get(x,99))


def clean(series):
    return series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():

    print("Loading 2011 TAZ...")
    taz11 = prepare(gpd.read_file(OLD_2011_TAZ_PATH))
    id11 = find_field(taz11, OLD_TAZ_ID_FIELD_CANDIDATES)
    taz11["TAZ_ID"] = clean(taz11[id11])

    print("Calculating 2011 metrics...")
    taz11["Old_Ac"] = taz11.geometry.area / 43560
    cen11 = taz11.geometry.centroid
    taz11["C11_X"] = cen11.x
    taz11["C11_Y"] = cen11.y

    taz11 = taz11[["TAZ_ID", "Old_Ac", "C11_X", "C11_Y"]]


    print("Loading 2020 assigned blocks...")
    blk = prepare(gpd.read_file(ASSIGNED_2020_BLOCKS_PATH))
    id20 = find_field(blk, BLOCK_TAZ_ID_FIELD_CANDIDATES)
    blk["TAZ_ID"] = clean(blk[id20])

    blk = blk[blk["TAZ_ID"].notna() & (blk["TAZ_ID"] != "")].copy()


    print("Reassembling TAZs...")
    taz20 = blk.dissolve(by="TAZ_ID", as_index=False)

    print("Calculating 2020 metrics...")
    taz20["New_Ac"] = taz20.geometry.area / 43560
    cen20 = taz20.geometry.centroid
    taz20["C20_X"] = cen20.x
    taz20["C20_Y"] = cen20.y

    taz20.to_file(OUTPUT_2020_REASSEMBLED_GPKG, driver="GPKG")


    print("Joining datasets...")
    comp = taz20.merge(taz11, on="TAZ_ID", how="left")


    print("Calculating differences...")
    comp["Ac_Chg"] = comp["New_Ac"] - comp["Old_Ac"]
    comp["Ac_Pct"] = (comp["Ac_Chg"] / comp["Old_Ac"]) * 100

    dx = comp["C20_X"] - comp["C11_X"]
    dy = comp["C20_Y"] - comp["C11_Y"]
    comp["Cent_Dist"] = ((dx**2 + dy**2) ** 0.5)


    print("Applying QA...")
    comp["AREA_FLAG"] = comp["Ac_Pct"].abs().apply(classify_area)
    comp["CENT_FLAG"] = comp["Cent_Dist"].apply(classify_cent)
    comp["QA_Flag"] = comp.apply(lambda r: worst_flag(r["AREA_FLAG"], r["CENT_FLAG"]), axis=1)

    comp["QA_Note"] = ""
    comp.loc[comp["QA_Flag"]=="OK","QA_Note"] = "Within tolerance"
    comp.loc[comp["QA_Flag"]=="MINOR","QA_Note"] = "Minor change"
    comp.loc[comp["QA_Flag"]=="MOD","QA_Note"] = "Moderate change - review"
    comp.loc[comp["QA_Flag"]=="MAJOR","QA_Note"] = "Major change - investigate"


    print("Cleaning output...")
    comp["Old_Ac"] = comp["Old_Ac"].round(2)
    comp["New_Ac"] = comp["New_Ac"].round(2)
    comp["Ac_Chg"] = comp["Ac_Chg"].round(2)
    comp["Ac_Pct"] = comp["Ac_Pct"].round(2)
    comp["Cent_Dist"] = comp["Cent_Dist"].round(1)


    comp = comp[
        [
            "TAZ_ID",
            "Old_Ac",
            "New_Ac",
            "Ac_Chg",
            "Ac_Pct",
            "Cent_Dist",
            "QA_Flag",
            "QA_Note",
            "geometry"
        ]
    ]


    print("Saving outputs...")
    comp.to_file(OUTPUT_COMPARISON_GPKG, driver="GPKG")
    comp.drop(columns="geometry").to_csv(OUTPUT_COMPARISON_CSV, index=False)


    print("Done.")
    print(comp["QA_Flag"].value_counts())


if __name__ == "__main__":
    main()