"""Writes an employee-import workbook with N rows, for the import load scenario.

    python infrastructure/loadtest/make_xlsx.py 150 small.xlsx
    python infrastructure/loadtest/make_xlsx.py 1000 large.xlsx

Needs openpyxl (the backend virtualenv has it). Addresses use the reserved .test domain, so no real mailbox exists.
"""

import sys

from openpyxl import Workbook

rows, target = int(sys.argv[1]), sys.argv[2]
prefix = sys.argv[3] if len(sys.argv) > 3 else "import"

workbook = Workbook()
sheet = workbook.active
sheet.append(["email", "full_name", "department", "role"])
for number in range(rows):
    sheet.append([f"{prefix}{number:05d}@load.test", f"Imported Person {number:05d}", "", "EMPLOYEE"])
workbook.save(target)
print(f"wrote {rows} rows to {target}")
