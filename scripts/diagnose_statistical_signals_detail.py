#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv
from collections import defaultdict
from datetime import datetime,time
from decimal import Decimal
from nse_paper_agent.domain.models import Bar,Regime
from nse_paper_agent.indicators.technical import sma,rsi

EVENT=time(13,55)
SYMBOLS={"ALPHA","BETA","GAMMA","DELTA","EPSILON"}

def main():
 p=argparse.ArgumentParser(); p.add_argument('--bars',required=True); p.add_argument('--limit',type=int,default=5); a=p.parse_args()
 h=defaultdict(list)
 rows=list(csv.DictReader(open(a.bars,newline='')))
 found=0
 for row in rows:
  b=Bar(row['symbol'],datetime.fromisoformat(row['start']),datetime.fromisoformat(row['end']),Decimal(row['open']),Decimal(row['high']),Decimal(row['low']),Decimal(row['close']),Decimal(row['volume']))
  h[b.symbol].append(b)
  if b.symbol in SYMBOLS and b.end.time().replace(tzinfo=None)==EVENT and b.end.date().isoformat()>='2025-04-30':
   closes=[x.close for x in h[b.symbol]]
   cur=sma(closes,20); prev=sma(closes[:-1],20); rv=rsi(closes,14)
   print({'symbol':b.symbol,'event':b.end.isoformat(),'prev_close':float(closes[-2]),'prev_sma20':float(prev) if prev else None,'close':float(b.close),'sma20':float(cur) if cur else None,'rsi14':rv,'cross':bool(cur is not None and prev is not None and closes[-1]>cur and closes[-2]<=prev)})
   found+=1
   if found>=a.limit: break
if __name__=='__main__': main()
