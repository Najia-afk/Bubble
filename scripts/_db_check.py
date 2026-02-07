import sys
sys.path.insert(0, '/app')
from config.settings import Config
from sqlalchemy import create_engine, func, inspect as sa_inspect
from sqlalchemy.orm import sessionmaker
from api.application.erc20models import WalletScore, WalletLabel, InvestigationTransfer

engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
s = sessionmaker(bind=engine)()

# Pure ORM queries — zero raw SQL
count = s.query(func.count(WalletScore.id)).scalar()
print(f'WalletScore count: {count}')

count2 = s.query(func.count(WalletScore.id)).filter(
    WalletScore.feature_tx_count.isnot(None),
    WalletScore.feature_tx_count > 0
).scalar()
print(f'WalletScore with features: {count2}')

count3 = s.query(func.count(WalletLabel.id)).filter(
    WalletLabel.confidence >= 0.8
).scalar()
print(f'WalletLabel high-conf: {count3}')

count4 = s.query(func.count(InvestigationTransfer.id)).scalar()
print(f'InvestigationTransfer count: {count4}')

# Check per-token tables using inspector
inspector = sa_inspect(engine)
tables = [t for t in inspector.get_table_names() if t.endswith('erc20_transfer_event')]
print(f'Per-token transfer tables: {tables}')

# Sample a WalletScore with features — pure ORM
rows = s.query(
    WalletScore.address,
    WalletScore.feature_tx_count,
    WalletScore.feature_unique_counterparties,
    WalletScore.predicted_type
).filter(WalletScore.feature_tx_count > 0).limit(5).all()
for row in rows:
    print(f'  Score: {row[0][:12]}... tx={row[1]} cp={row[2]} type={row[3]}')

s.close()
