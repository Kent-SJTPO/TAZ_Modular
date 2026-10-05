from pathlib import Path
import fitz
import pandas as pd
import re

# ============================================================
# Configuration
# ============================================================

INPUT_FOLDER = Path(r"J:\Data Inventory\Traffic Counts\Imperial\02_May ATRs")

OUTPUT_CSV = INPUT_FOLDER / "ATR_Locations.csv"
FAIL_CSV = INPUT_FOLDER / "ATR_Failures.csv"

# ============================================================
# Main
# ============================================================

records = []
failures = []

pdf_files = sorted(INPUT_FOLDER.rglob("*.pdf"))

print(f"\nFound {len(pdf_files)} PDF files\n")

for pdf in pdf_files:

    if "VOID" in pdf.parts:
        continue

    print("=" * 70)
    print(f"Processing: {pdf.relative_to(INPUT_FOLDER)}")

    try:

        doc = fitz.open(pdf)

        full_text = ""

        for page in doc:
            full_text += page.get_text("text") + "\n"

        doc.close()

        # ----------------------------------------------------
        # Find ALL latitude and longitude values
        # ----------------------------------------------------

        latitudes = re.findall(r"39\.\d+", full_text)
        longitudes = re.findall(r"-7\d\.\d+", full_text)

        print(f"Latitudes Found : {latitudes}")
        print(f"Longitudes Found: {longitudes}")

        if len(latitudes) > 0 and len(longitudes) > 0:

            records.append(
                {
                    "PDF_File": pdf.name,
                    "Folder": str(pdf.parent.relative_to(INPUT_FOLDER)),
                    "Latitude": latitudes[0],
                    "Longitude": longitudes[0]
                }
            )

            print("SUCCESS")

        else:

            failures.append(
                {
                    "PDF_File": pdf.name,
                    "Folder": str(pdf.parent.relative_to(INPUT_FOLDER))
                }
            )

            print("*** NO COORDINATES FOUND ***")

    except Exception as ex:

        failures.append(
            {
                "PDF_File": pdf.name,
                "Folder": str(pdf.parent.relative_to(INPUT_FOLDER))
            }
        )

        print(f"ERROR: {ex}")

# ============================================================
# Write Results
# ============================================================

if len(records) > 0:

    df = pd.DataFrame(records)

    df.sort_values(
        ["Folder", "PDF_File"],
        inplace=True
    )

    df.to_csv(
        OUTPUT_CSV,
        index=False
    )

    print("\n")
    print("=" * 70)
    print(f"Locations written: {len(df)}")
    print(OUTPUT_CSV)

else:

    print("\nNo locations extracted.")

if len(failures) > 0:

    fail = pd.DataFrame(failures)

    fail.sort_values(
        ["Folder", "PDF_File"],
        inplace=True
    )

    fail.to_csv(
        FAIL_CSV,
        index=False
    )

    print(f"Failures written: {len(fail)}")
    print(FAIL_CSV)

else:

    print("No failures.")