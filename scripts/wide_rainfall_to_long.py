"""Convert a wide subdivision x year x month rainfall CSV into the long format the app imports.

Input columns:  SUBDIVISION, YEAR, JAN..DEC (+ ANNUAL and seasonal totals, which are ignored).
Output columns: date, region, variable, value, unit

Nothing is invented: blank / "NA" month cells are dropped (they stay missing), and the
ANNUAL / seasonal columns are not copied because they are sums of the months.

Usage: python -I scripts/wide_rainfall_to_long.py <input.csv> <output.csv> [unit]
"""
import csv
import sys

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def main(src: str, dst: str, unit: str = "mm/month") -> None:
    kept = dropped = 0
    with open(src, encoding="utf-8-sig", newline="") as f, open(dst, "w", encoding="utf-8", newline="") as out:
        w = csv.writer(out)
        w.writerow(["date", "region", "variable", "value", "unit"])
        for row in csv.DictReader(f):
            region = row["SUBDIVISION"].strip().title()
            year = int(row["YEAR"])
            for i, m in enumerate(MONTHS, start=1):
                raw = (row.get(m) or "").strip()
                try:
                    v = float(raw)
                except ValueError:
                    dropped += 1
                    continue
                w.writerow([f"{year}-{i:02d}-01", region, "Rainfall", v, unit])
                kept += 1
    print(f"wrote {kept} rows, skipped {dropped} missing month cells -> {dst}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(*sys.argv[1:4])
