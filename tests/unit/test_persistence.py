from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
def test_transaction_failure_rolls_back(tmp_path):
 db=Database(str(tmp_path/'x.sqlite')); db.initialize(); r=Repository(db); r.set_cash(50000)
 try:
  with db.transaction(): db.conn.execute("INSERT INTO positions VALUES('ABC',1,100,98.5,105,20,'v1','2026-01-01T00:00:00+00:00',100)"); raise RuntimeError('rollback')
 except RuntimeError: pass
 assert not r.positions(); db.close()
