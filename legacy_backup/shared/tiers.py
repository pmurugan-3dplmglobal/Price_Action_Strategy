
def calculate_tiered_rr(entry, sl, t1, t2, t3, pattern_type='bull'):
    if pattern_type == 'bull':
        risk = entry - sl
        if risk <= 0:
            return (0, None, None)
        if t1 is not None and t1 > entry:
            rr = (t1 - entry) / risk
            if rr >= 1.5:
                return (round(rr, 2), t1, 'T1')
        if t2 is not None and t2 > entry:
            rr = (t2 - entry) / risk
            if rr >= 1.5:
                return (round(rr, 2), t2, 'T2')
        if t3 is not None and t3 > entry:
            rr = (t3 - entry) / risk
            if rr >= 1.5:
                return (round(rr, 2), t3, 'T3')
    else:
        risk = sl - entry
        if risk <= 0:
            return (0, None, None)
        if t1 is not None and t1 < entry:
            rr = (entry - t1) / risk
            if rr >= 1.5:
                return (round(rr, 2), t1, 'T1')
        if t2 is not None and t2 < entry:
            rr = (entry - t2) / risk
            if rr >= 1.5:
                return (round(rr, 2), t2, 'T2')
        if t3 is not None and t3 < entry:
            rr = (entry - t3) / risk
            if rr >= 1.5:
                return (round(rr, 2), t3, 'T3')
    return (0, None, None)
