"""Quick DB audit — check what data we actually have for ML."""
import psycopg2

conn = psycopg2.connect('postgresql://bubble_user:bubble_password@localhost:5432/bubble_db')
cur = conn.cursor()

# All tables with row counts
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
tables = [r[0] for r in cur.fetchall()]
print('=== TABLES ===')
for t in tables:
    cur.execute(f'SELECT COUNT(*) FROM "{t}"')
    cnt = cur.fetchone()[0]
    if cnt > 0:
        print(f'  {t}: {cnt} rows')

print()

# Cases
cur.execute('SELECT id, title, status FROM cases ORDER BY id')
print('=== CASES ===')
for r in cur.fetchall():
    print(f'  id={r[0]} title="{r[1][:50]}" status={r[2]}')

print()

# Investigations
cur.execute('SELECT id, case_id, status FROM investigations ORDER BY id')
print('=== INVESTIGATIONS ===')
for r in cur.fetchall():
    print(f'  inv_id={r[0]} case_id={r[1]} status={r[2]}')

print()

# Investigation wallets per investigation
cur.execute("""
    SELECT investigation_id, COUNT(*) as cnt, 
           COUNT(DISTINCT wallet_type) as types
    FROM investigation_wallets 
    GROUP BY investigation_id ORDER BY investigation_id
""")
print('=== INVESTIGATION WALLETS ===')
for r in cur.fetchall():
    print(f'  inv_id={r[0]}: {r[1]} wallets, {r[2]} types')

print()

# Wallet types distribution
cur.execute("""
    SELECT wallet_type, COUNT(*) 
    FROM investigation_wallets 
    GROUP BY wallet_type 
    ORDER BY COUNT(*) DESC
""")
print('=== WALLET TYPE DISTRIBUTION ===')
for r in cur.fetchall():
    print(f'  {r[0]}: {r[1]}')

print()

# Transfers per investigation
cur.execute("""
    SELECT investigation_id, COUNT(*) 
    FROM transfers 
    GROUP BY investigation_id 
    ORDER BY investigation_id
""")
print('=== TRANSFERS ===')
for r in cur.fetchall():
    print(f'  inv_id={r[0]}: {r[1]} transfers')

print()

# Wallet scores
cur.execute('SELECT COUNT(*) FROM wallet_scores')
score_count = cur.fetchone()[0]
print(f'=== WALLET SCORES: {score_count} ===')
if score_count > 0:
    cur.execute("SELECT predicted_type, COUNT(*) FROM wallet_scores GROUP BY predicted_type ORDER BY COUNT(*) DESC")
    for r in cur.fetchall():
        print(f'  {r[0]}: {r[1]}')

print()

# Model metadata
cur.execute('SELECT COUNT(*) FROM model_metadata')
model_count = cur.fetchone()[0]
print(f'=== MODEL METADATA: {model_count} ===')
if model_count > 0:
    cur.execute("SELECT id, model_type, status, accuracy, f1_score FROM model_metadata ORDER BY id DESC LIMIT 5")
    for r in cur.fetchall():
        print(f'  id={r[0]} type={r[1]} status={r[2]} acc={r[3]} f1={r[4]}')

conn.close()
