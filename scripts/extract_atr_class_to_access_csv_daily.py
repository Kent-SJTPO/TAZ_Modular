# extract_atr_class_to_access_csv.py
# Purpose:
#   Extract hourly vehicle classification data from an ATR Excel workbook and
#   write Access-ready CSV files matching these target tables:
#     tblClassByHour
#     tblTrafficStations
#
# Corrected logic:
#   The earlier version aggregated all collection days into one 24-hour row.
#   This version preserves each collected day.
#
# Because tblClassByHour does not have a CountDate field, the default behavior
# is to treat each Station + Date as a separate Station value:
#
#   Station = "SJTPO ATR 5 2026-05-05"
#
# This keeps the CSV headers compatible with the existing Access table fields.
# If you later add a CountDate field to tblClassByHour, this script can be
# simplified to store the date in its own field instead.
#
# H01 = 12:00 AM through 12:59 AM
# H02 = 1:00 AM through 1:59 AM
# ...
# H24 = 11:00 PM through 11:59 PM
#
# Requires:
#   pip install openpyxl

from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------

INPUT_XLSX = Path(r"/mnt/data/ATR 5. Deliah Road, near Wawa & Southern Driveway_60 Minute.xlsx")
OUTPUT_FOLDER = Path(r"/mnt/data")

DEFAULT_COUNTY = "Atlantic"
DEFAULT_COUNTY_ORDER = 1
DEFAULT_STATION_TYPE = "ATR"
DEFAULT_ROUTE = "Deliah Road"

CLASS_SHEETS = [
    "Motorcycles",
    "Lights",
    "Single-Unit Trucks",
    "Articulated Trucks",
    "Buses",
    "Bicycles on Road",
]

CLASS_OUTPUT_NAME = "tblClassByHour_import_daily.csv"
STATION_OUTPUT_NAME = "tblTrafficStations_import_daily.csv"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def safe_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if value is None or value == "":
        return None

    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M %p",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def access_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%m/%d/%Y %I:%M:%S %p")


def read_summary(wb: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if "Summary" not in wb.sheetnames:
        return summary

    ws = wb["Summary"]
    for row in ws.iter_rows(min_row=1, max_col=2, values_only=True):
        key = clean_text(row[0])
        if key:
            summary[key] = row[1]
    return summary


def derive_station_id(summary: dict[str, Any]) -> str:
    location = clean_text(summary.get("Location"))
    if location:
        return location

    study_name = clean_text(summary.get("Study Name"))
    match = re.search(r"\bATR\s*\d+\b", study_name, flags=re.IGNORECASE)
    if match:
        return match.group(0).upper().replace("  ", " ")

    return study_name or "UNKNOWN"


def derive_description(summary: dict[str, Any]) -> str:
    study_name = clean_text(summary.get("Study Name"))
    return study_name[:255]


def station_day_id(base_station_id: str, count_date: date) -> str:
    return f"{base_station_id} {count_date.isoformat()}"


def read_hourly_by_day(ws: Any) -> tuple[dict[date, dict[int, int]], dict[date, int], datetime | None, datetime | None]:
    # Rows 1-3 are headers. Data starts on row 4.
    # Column A = Start Time. Columns B:E = lane volumes for both directions.
    hourly_by_day: dict[date, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    records_by_day: dict[date, int] = defaultdict(int)
    first_dt: datetime | None = None
    last_dt: datetime | None = None

    for row in ws.iter_rows(min_row=4, values_only=True):
        start_dt = as_datetime(row[0])
        if start_dt is None:
            continue

        count_date = start_dt.date()
        hour_num = start_dt.hour + 1
        row_total = sum(safe_int(v) for v in row[1:])

        hourly_by_day[count_date][hour_num] += row_total
        records_by_day[count_date] += 1

        if first_dt is None or start_dt < first_dt:
            first_dt = start_dt
        if last_dt is None or start_dt > last_dt:
            last_dt = start_dt

    return hourly_by_day, records_by_day, first_dt, last_dt


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    if not INPUT_XLSX.exists():
        raise FileNotFoundError(f"Input workbook not found: {INPUT_XLSX}")

    wb = load_workbook(INPUT_XLSX, data_only=True, read_only=True)
    summary = read_summary(wb)

    base_station_id = derive_station_id(summary)
    description = derive_description(summary)
    source_file = INPUT_XLSX.name

    # all_data[count_date][vehicle_class][hour_number] = volume
    all_data: dict[date, dict[str, dict[int, int]]] = defaultdict(dict)
    records_by_station_day: dict[date, int] = defaultdict(int)
    first_by_day: dict[date, datetime] = {}
    last_by_day: dict[date, datetime] = {}

    for sheet_name in CLASS_SHEETS:
        if sheet_name not in wb.sheetnames:
            print(f"WARNING: Missing expected class sheet: {sheet_name}")
            continue

        ws = wb[sheet_name]
        hourly_by_day, records_by_day, first_dt, last_dt = read_hourly_by_day(ws)

        for count_date, hourly_totals in hourly_by_day.items():
            all_data[count_date][sheet_name] = dict(hourly_totals)
            records_by_station_day[count_date] += records_by_day[count_date]

            day_first = datetime.combine(count_date, time.min)
            day_last = day_first + timedelta(days=1)

            if count_date not in first_by_day or day_first < first_by_day[count_date]:
                first_by_day[count_date] = day_first
            if count_date not in last_by_day or day_last > last_by_day[count_date]:
                last_by_day[count_date] = day_last

    class_rows: list[dict[str, Any]] = []
    station_rows: list[dict[str, Any]] = []

    class_order = {name: i for i, name in enumerate(CLASS_SHEETS)}

    for count_date in sorted(all_data):
        daily_station = station_day_id(base_station_id, count_date)

        for vehicle_class in sorted(all_data[count_date], key=lambda x: class_order.get(x, 999)):
            hourly_totals = all_data[count_date][vehicle_class]
            row: dict[str, Any] = {
                "Station": daily_station,
                "VehicleClass": vehicle_class,
                "Total": sum(hourly_totals.values()),
                "SourceFile": source_file,
                "SourceSheet": vehicle_class,
            }
            for h in range(1, 25):
                row[f"H{h:02d}"] = hourly_totals.get(h, 0)
            class_rows.append(row)

        station_rows.append({
            "County": DEFAULT_COUNTY,
            "StationID": daily_station,
            "FirstDate": access_datetime(first_by_day.get(count_date)),
            "LastDate": access_datetime(last_by_day.get(count_date)),
            "RecordsLoaded": records_by_station_day[count_date],
            "DaysCollected": 1,
            "StationType": DEFAULT_STATION_TYPE,
            "Route": DEFAULT_ROUTE,
            "Description": f"{description} - {count_date.isoformat()}"[:255],
            "CountyOrder": DEFAULT_COUNTY_ORDER,
        })

    class_fields = [
        "Station",
        "VehicleClass",
        *[f"H{h:02d}" for h in range(1, 25)],
        "Total",
        "SourceFile",
        "SourceSheet",
    ]

    station_fields = [
        "County",
        "StationID",
        "FirstDate",
        "LastDate",
        "RecordsLoaded",
        "DaysCollected",
        "StationType",
        "Route",
        "Description",
        "CountyOrder",
    ]

    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    class_csv = OUTPUT_FOLDER / CLASS_OUTPUT_NAME
    station_csv = OUTPUT_FOLDER / STATION_OUTPUT_NAME

    write_csv(class_csv, class_fields, class_rows)
    write_csv(station_csv, station_fields, station_rows)

    print("Wrote:")
    print(f"  {class_csv}")
    print(f"  {station_csv}")
    print("")
    print("Base station:", base_station_id)
    print("Station-days written:", len(station_rows))
    print("Class rows written:", len(class_rows))
    print("Expected class rows = station-days x classes present")
    print("RecordsLoaded:", sum(records_by_station_day.values()))


if __name__ == "__main__":
    main()
