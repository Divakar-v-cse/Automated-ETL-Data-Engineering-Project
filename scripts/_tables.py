import sqlite3

c = sqlite3.connect("data/db/warehouse.db")
names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("TABLES", len(names))
for n in names:
    print(" ", n)
print()
for t in names:
    if "qual" in t or "quarant" in t or "report" in t:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        cnt = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(t, cnt, cols)
