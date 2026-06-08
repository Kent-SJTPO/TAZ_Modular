# extract_60_Minute_atr_class_to_access_csv_daily.py

from __future__ import annotations

import csv
import re
import shutil
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


SOURCE_FOLDER = Path(
    r"J:\Data Inventory\Traffic Counts\Imperial\ATR Format\60 Minute"
)

ROOT_FOLDER = Path(
    r"C:\Users\Kschellinger\SJTPO_Git\TAZ_Modular\traffic_counts"
)

INPUT_FOLDER = ROOT_FOLDER
OUTPUT_FOLDER = ROOT_FOLDER / "processed"

INPUT_PATTERN = "*60 Minute*.xlsx"

CLASS_OUTPUT_NAME = "tblClassByHour_import_daily.txt"
STATION_OUTPUT_NAME = "tblTrafficStations_import_daily.txt"
LOG_OUTPUT_NAME = "processing_log.txt"

DEFAULT_COUNTY = ""
DEFAULT_COUNTY_ORDER = ""
DEFAULT_STATION_TYPE = "ATR"
DEFAULT_ROUTE = ""

CLASS_SHEETS = [
    "Motorcycles",
    "Lights",
    "Single-Unit Trucks",
    "Articulated Trucks",
    "Buses",
    "Bicycles on Road",
]


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
        pass

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

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M %p",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return None


def access_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%m/%d/%Y %I:%M:%S %p")


def access_date(value: date | None) -> str:
    if value is None:
        return ""
    return value.strftime("%m/%d/%Y")


def read_summary(wb: Any) -> dict[str, Any]:
    summary = {}

    if "Summary" not in wb.sheetnames:
        return summary

    ws = wb["Summary"]

    for row in ws.iter_rows(min_row=1, max_col=2, values_only=True):
        key = clean_text(row[0])
        value = row[1]

        if key:
            summary[key] = value

    return summary


def remove_provider_atr_prefix(text: str) -> str:
    text = clean_text(text)

    text = re.sub(
        r"^\s*ATR\s*\d+\s*[\.\-_:]*\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"^\s*SJTPO\s+ATR\s*\d+\s*[\.\-_:]*\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return text.strip()


def derive_base_station_id(summary: dict[str, Any], source_file: Path) -> str:
    study_name = clean_text(summary.get("Study Name"))
    station = remove_provider_atr_prefix(study_name)

    if station:
        return station[:255]

    name = source_file.stem
    name = re.sub(r"_60\s*Minute$", "", name, flags=re.IGNORECASE)
    station = remove_provider_atr_prefix(name)

    if station:
        return station[:255]

    return "UNKNOWN"


def derive_description(summary: dict[str, Any], source_file: Path) -> str:
    study_name = clean_text(summary.get("Study Name"))

    if study_name:
        return study_name[:255]

    return source_file.stem[:255]


def read_hourly_by_day(ws: Any) -> tuple[dict[date, dict[int, int]], dict[date, int]]:
    hourly_by_day = defaultdict(lambda: defaultdict(int))
    records_by_day = defaultdict(int)

    for row in ws.iter_rows(min_row=4, values_only=True):
        start_dt = as_datetime(row[0])

        if start_dt is None:
            continue

        count_date = start_dt.date()
        hour_number = start_dt.hour + 1

        row_total = sum(safe_int(value) for value in row[1:])

        hourly_by_day[count_date][hour_number] += row_total
        records_by_day[count_date] += 1

    return hourly_by_day, records_by_day


def write_delimited(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            delimiter="\t",
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
            extrasaction="ignore",
        )

        writer.writeheader()

        for row in rows:
            writer.writerow(row)


def write_log(path: Path, lines: list[str]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for line in lines:
            file.write(line + "\n")


def copy_source_workbooks_to_input(log_lines: list[str]) -> list[Path]:
    copied_files = []

    if not SOURCE_FOLDER.exists():
        raise FileNotFoundError(f"Source folder not found: {SOURCE_FOLDER}")

    INPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    source_files = sorted(SOURCE_FOLDER.glob(INPUT_PATTERN))

    if not source_files:
        raise FileNotFoundError(
            f"No source files found matching {INPUT_PATTERN} in {SOURCE_FOLDER}"
        )

    for source_path in source_files:
        target_path = INPUT_FOLDER / source_path.name

        if target_path.exists():
            msg = f"Already local, skipped copy: {source_path.name}"
            print(msg)
            log_lines.append(msg)
            continue

        shutil.copy2(source_path, target_path)
        copied_files.append(target_path)

        msg = f"Copied: {source_path.name}"
        print(msg)
        log_lines.append(msg)

    return copied_files


def process_workbook(
    xlsx_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], bool]:

    warnings = []
    class_rows = []
    station_rows = []
    success = False

    wb = None

    try:
        wb = load_workbook(xlsx_path, data_only=True, read_only=True)

        summary = read_summary(wb)

        base_station_id = derive_base_station_id(summary, xlsx_path)
        description = derive_description(summary, xlsx_path)
        source_file = xlsx_path.name

        all_data = defaultdict(dict)
        records_by_station_day = defaultdict(int)

        for sheet_name in CLASS_SHEETS:
            if sheet_name not in wb.sheetnames:
                warnings.append(
                    f"WARNING {xlsx_path.name}: missing expected sheet: {sheet_name}"
                )
                continue

            ws = wb[sheet_name]
            hourly_by_day, records_by_day = read_hourly_by_day(ws)

            for count_date, hourly_totals in hourly_by_day.items():
                all_data[count_date][sheet_name] = dict(hourly_totals)
                records_by_station_day[count_date] += records_by_day[count_date]

        class_order = {name: index for index, name in enumerate(CLASS_SHEETS)}

        for count_date in sorted(all_data):
            for vehicle_class in sorted(
                all_data[count_date],
                key=lambda value: class_order.get(value, 999),
            ):
                hourly_totals = all_data[count_date][vehicle_class]

                row = {
                    "Station": base_station_id,
                    "CountDate": access_date(count_date),
                    "VehicleClass": vehicle_class,
                    "Total": sum(hourly_totals.values()),
                    "SourceFile": source_file,
                    "SourceSheet": vehicle_class,
                }

                for hour in range(1, 25):
                    row[f"H{hour:02d}"] = hourly_totals.get(hour, 0)

                class_rows.append(row)

            first_dt = datetime.combine(count_date, time.min)
            last_dt = first_dt + timedelta(days=1)

            station_rows.append(
                {
                    "County": DEFAULT_COUNTY,
                    "StationID": base_station_id,
                    "FirstDate": access_datetime(first_dt),
                    "LastDate": access_datetime(last_dt),
                    "RecordsLoaded": records_by_station_day[count_date],
                    "DaysCollected": 1,
                    "StationType": DEFAULT_STATION_TYPE,
                    "Route": DEFAULT_ROUTE,
                    "Description": description,
                    "CountyOrder": DEFAULT_COUNTY_ORDER,
                }
            )

        if not class_rows:
            warnings.append(f"WARNING {xlsx_path.name}: no class rows extracted")
            return class_rows, station_rows, warnings, success

        success = True
        return class_rows, station_rows, warnings, success

    except Exception as exc:
        warnings.append(f"SKIPPED {xlsx_path.name}: processing failed: {exc}")
        return class_rows, station_rows, warnings, success

    finally:
        if wb is not None:
            try:
                wb.close()
            except Exception:
                pass


def main() -> None:
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    log_lines = []

    log_lines.append(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_lines.append(f"Source folder: {SOURCE_FOLDER}")
    log_lines.append(f"Input folder: {INPUT_FOLDER}")
    log_lines.append(f"Output folder: {OUTPUT_FOLDER}")
    log_lines.append(f"Pattern: {INPUT_PATTERN}")
    log_lines.append("")

    print(f"Source folder: {SOURCE_FOLDER}")
    print(f"Input folder: {INPUT_FOLDER}")
    print(f"Output folder: {OUTPUT_FOLDER}")
    print(f"Pattern: {INPUT_PATTERN}")
    print("")

    copied_files = copy_source_workbooks_to_input(log_lines)

    files = sorted(INPUT_FOLDER.glob(INPUT_PATTERN))

    if not files:
        raise FileNotFoundError(
            f"No local files found matching {INPUT_PATTERN} in {INPUT_FOLDER}"
        )

    all_class_rows = []
    all_station_rows = []
    all_warnings = []

    log_lines.append("")
    log_lines.append(f"Source files copied: {len(copied_files)}")
    log_lines.append(f"Local workbook count: {len(files)}")
    log_lines.append("")

    print("")
    print(f"Source files copied: {len(copied_files)}")
    print(f"Local workbook count: {len(files)}")
    print("")

    processed_files = 0

    for xlsx_path in files:
        msg = f"Processing: {xlsx_path.name}"
        print(msg)
        log_lines.append(msg)

        class_rows, station_rows, warnings, success = process_workbook(xlsx_path)

        all_class_rows.extend(class_rows)
        all_station_rows.extend(station_rows)
        all_warnings.extend(warnings)

        print(f"  Station-day rows: {len(station_rows)}")
        print(f"  Class rows:       {len(class_rows)}")
        print("  Archive step skipped")

        log_lines.append(f"  Station-day rows: {len(station_rows)}")
        log_lines.append(f"  Class rows:       {len(class_rows)}")
        log_lines.append("  Archive step skipped")

        if success:
            processed_files += 1

        print("")
        log_lines.append("")

    class_fields = [
        "Station",
        "CountDate",
        "VehicleClass",
        "H01",
        "H02",
        "H03",
        "H04",
        "H05",
        "H06",
        "H07",
        "H08",
        "H09",
        "H10",
        "H11",
        "H12",
        "H13",
        "H14",
        "H15",
        "H16",
        "H17",
        "H18",
        "H19",
        "H20",
        "H21",
        "H22",
        "H23",
        "H24",
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

    class_txt = OUTPUT_FOLDER / CLASS_OUTPUT_NAME
    station_txt = OUTPUT_FOLDER / STATION_OUTPUT_NAME
    log_file = OUTPUT_FOLDER / LOG_OUTPUT_NAME

    write_delimited(class_txt, class_fields, all_class_rows)
    write_delimited(station_txt, station_fields, all_station_rows)

    log_lines.append("Final summary")
    log_lines.append("------------------------------")
    log_lines.append(f"Source files copied:     {len(copied_files)}")
    log_lines.append(f"Workbooks found locally: {len(files)}")
    log_lines.append(f"Workbooks processed:     {processed_files}")
    log_lines.append(f"Station-day rows:        {len(all_station_rows)}")
    log_lines.append(f"Class rows:              {len(all_class_rows)}")
    log_lines.append(f"Class TXT:               {class_txt}")
    log_lines.append(f"Station TXT:             {station_txt}")

    if all_warnings:
        log_lines.append("")
        log_lines.append("Warnings")
        log_lines.append("------------------------------")
        for warning in all_warnings:
            log_lines.append(warning)

    write_log(log_file, log_lines)

    print("Wrote:")
    print(f"  {class_txt}")
    print(f"  {station_txt}")
    print(f"  {log_file}")
    print("")
    print(f"Workbooks processed: {processed_files}")
    print(f"Station-day rows:    {len(all_station_rows)}")
    print(f"Class rows:          {len(all_class_rows)}")

    if all_warnings:
        print("")
        print("Warnings were written to the processing log.")


if __name__ == "__main__":
    main()