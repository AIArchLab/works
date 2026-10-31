#!/usr/bin/env python3
"""Generate synthetic test data (1,000 detail rows) and the expected_truth.json answer key.
Deterministic: fixed seed, fully reproducible. All data is fictional."""
import csv, json, random
from openpyxl import Workbook

random.seed(42)
N_AGENTS, PER_AGENT = 50, 20
truth = {}
with open("fixtures/fixture_B_detail.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["Policy date", "Product line", "Emp no", "Premium"])  # deliberately different names/order
    for i in range(1, N_AGENTS + 1):
        aid = f"A{i:04d}"
        total = 0.0
        for j in range(PER_AGENT):
            amt = round(random.uniform(800, 9000), 0)
            total += amt
            w.writerow([f"2026/{(j % 9) + 1:02d}/{(i % 27) + 1:02d}", ["Life", "Property", "Medical"][j % 3], aid, int(amt)])
        truth[aid] = int(total)
wb = Workbook(); ws = wb.active
ws.append(["Name", "Date", "Agent ID", "Item", "Monthly sales"])  # another header set/order
for i in range(1, N_AGENTS + 1):
    aid = f"A{i:04d}"
    ws.append([f"Agent {i:02d}", "2026-10-31", aid, "Monthly close", truth[aid]])
wb.save("fixtures/fixture_A_summary.xlsx")
json.dump(truth, open("fixtures/expected_truth.json", "w"), indent=0)
print(f"generated fixture_A_summary.xlsx (50 rows) / fixture_B_detail.csv ({N_AGENTS*PER_AGENT} rows) / expected_truth.json")
