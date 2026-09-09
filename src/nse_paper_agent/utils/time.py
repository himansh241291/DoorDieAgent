from datetime import datetime,timezone
from zoneinfo import ZoneInfo
IST=ZoneInfo("Asia/Kolkata"); UTC=timezone.utc
def utcnow(): return datetime.now(UTC)
def to_ist(ts): return ts.astimezone(IST)
