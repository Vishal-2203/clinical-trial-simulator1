import sqlite3
conn = sqlite3.connect('chembl_37/chembl_37_sqlite/chembl_37.db')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'organ%'")
print("Organism tables:", cur.fetchall())
cur.execute("PRAGMA table_info(organism_class)")
print("organism_class cols:", cur.fetchall()[:5])
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'target%'")
print("Target tables:", cur.fetchall())
