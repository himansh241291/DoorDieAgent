from __future__ import annotations
from datetime import datetime
from typing import Protocol
from nse_paper_agent.domain.models import SentimentObservation
class SentimentProvider(Protocol):
    def market(self,now:datetime)->SentimentObservation: ...
    def symbol(self,symbol:str,now:datetime)->SentimentObservation: ...
class NeutralSentimentProvider:
    def market(self,now): return SentimentObservation("NIFTY50",now,None,0.0,"unavailable",None,{})
    def symbol(self,symbol,now): return SentimentObservation(symbol,now,None,0.0,"unavailable",None,{})
class CompositeSentiment:
    def __init__(self,weights): self.weights=weights
    def score(self,trend,breadth,relative_strength,volume_confirmation,news):
        n=0.0 if news is None else news; w=self.weights; score=w["trend"]*trend+w["breadth"]*breadth+w["relative_strength"]*relative_strength+w["volume_confirmation"]*volume_confirmation+w["news"]*n; return max(-1.0,min(1.0,score))
