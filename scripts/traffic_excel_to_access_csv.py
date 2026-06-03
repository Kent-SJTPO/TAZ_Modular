from pathlib import Path
import pandas as pd
import re

INPUT_FOLDER = Path(
    r"C:\Users\Kschellinger\SJTPO_Git\TAZ_Modular\traffic_counts\input_xlsx"
)

OUTPUT_CSV = INPUT_FOLDER.parent / "traffic_counts_access_import.csv"

INPUT_FILES = [
    "Atlantic County May Aug 2025.xlsx",
    "Burlington County May Aug 2025.xlsx",
    "Camden County May Aug 2025.xlsx",
    "Cape May County May Aug 2025.xlsx",
    "Cumberland County May Aug 2025.xlsx",
    "Gloucester County May Aug 2025.xlsx",
    "Salem County May Aug 2025.xlsx",
]

MONTHS = {"May", "Jun", "Jul", "Aug"}
HOUR_COLUMNS = [f"H{i:02d}" for i in range(1, 25)]

records = []

for file_name in INPUT_FILES:
    xlsx_path = INPUT_FOLDER / file_name

    if not xlsx_path.exists():
        print(f"Missing file: {xlsx_path}")
        continue

    county_from_file = file_name.split(" County")[0].strip()

    print(f"\nProcessing: {file_name}")

    xl = pd.ExcelFile(xlsx_path, engine="openpyxl")

    for sheet in xl.sheet_names:
        if "map" in sheet.lower():
            continue

        m = re.match(r"(.+?)_(May|Jun|Jul|Aug)$", sheet.strip())

        if not m:
            print(f"Skipping unexpected sheet name: {file_name} / {sheet}")
            continue

        station_id = m.group(1).strip()
        sheet_month = m.group(2).strip()

        df = pd.read_excel(
            xlsx_path,
            sheet_name=sheet,
            header=14,
            engine="openpyxl",
        )

        df = df.rename(columns=lambda c: str(c).strip())

        needed = ["Date", "DIR", "DOW", "Total", "Status"] + HOUR_COLUMNS
        missing = [c for c in needed if c not in df.columns]

        if missing:
            print(f"Missing columns in {file_name} / {sheet}: {missing}")
            continue

        df = df[needed].copy()
        df = df[df["Date"].notna()]

        for _, row in df.iterrows():
            count_date = pd.to_datetime(row["Date"], errors="coerce")

            if pd.isna(count_date):
                continue

            for hour_col in HOUR_COLUMNS:
                hour_beginning = int(hour_col[1:]) - 1

                records.append(
                    {
                        "County": county_from_file,
                        "StationID": station_id,
                        "SheetMonth": sheet_month,
                        "CountDate": count_date.strftime("%m/%d/%Y"),
                        "Direction": row["DIR"],
                        "DayOfWeek": row["DOW"],
                        "HourEnding": hour_col,
                        "HourBeginning": hour_beginning,
                        "Volume": row[hour_col],
                        "DailyTotal": row["Total"],
                        "Status": row["Status"],
                        "SourceWorkbook": file_name,
                        "SourceSheet": sheet,
                    }
                )

if not records:
    print("\nNo records were created.")
    print(f"Input folder checked: {INPUT_FOLDER}")
    raise SystemExit("Stopped because no usable data was found.")

out = pd.DataFrame(records)

out = out.sort_values(
    ["County", "StationID", "CountDate", "Direction", "HourBeginning"]
)

out.to_csv(OUTPUT_CSV, index=False)

print("\nDone.")
print(f"Rows written: {len(out):,}")
print(f"Output file: {OUTPUT_CSV}")