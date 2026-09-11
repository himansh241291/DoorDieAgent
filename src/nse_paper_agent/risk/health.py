from datetime import timedelta
class DataHealth:
    def __init__(self,max_age_seconds=30,max_spread_bps=50):
        self.max_age=timedelta(seconds=max_age_seconds)
        self.max_spread_bps=max_spread_bps

    def check_quote(self,q,now):
        if now-q.ts>self.max_age:
            return False,"stale_quote"

        for x in (q.bid,q.ask,q.last):
            if x is not None and x<=0:
                return False,"non_positive_quote"

        if q.bid is not None and q.ask is not None:
            if q.ask<q.bid:
                return False,"crossed_quote"

            mid=(q.ask+q.bid)/2

            if mid>0 and float((q.ask-q.bid)/mid*10000)>self.max_spread_bps:
                return False,"spread_too_wide"

        if q.bid is None and q.ask is None and q.last is None:
            return False,"no_price"

        return True,"healthy"

    def check_exit_price(self,q):
        """Validate only whether a usable conservative exit price exists."""
        for x in (q.bid,q.last):
            if x is not None and x<=0:
                return False,"non_positive_exit_price"

        if q.bid is not None:
            return True,"bid_available"

        if q.last is not None:
            return True,"last_price_fallback"

        return False,"no_exit_price"
