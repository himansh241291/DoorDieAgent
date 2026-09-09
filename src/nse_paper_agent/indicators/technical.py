from __future__ import annotations
from decimal import Decimal
def sma(values:list[Decimal],period:int)->Decimal|None:
    if len(values)<period: return None
    return sum(values[-period:],Decimal(0))/Decimal(period)
def rsi(values:list[Decimal],period:int=14)->float|None:
    if len(values)<period+1: return None
    gains=[]; losses=[]
    for a,b in zip(values[-period-1:-1],values[-period:]):
        d=b-a; gains.append(max(d,Decimal(0))); losses.append(max(-d,Decimal(0)))
    ag=float(sum(gains))/period; al=float(sum(losses))/period
    if al==0: return 100.0
    return 100.0-(100.0/(1.0+ag/al))
def true_range(prev_close:Decimal,high:Decimal,low:Decimal)->Decimal:
    return max(high-low,abs(high-prev_close),abs(low-prev_close))
