"""Describe already decoded archive partitions; never fetch or infer closures."""
def summarize(partitions):
    streams=[]
    for name,rows in sorted(partitions.items()):
        provider,pair,tf,month=name.split('/')
        stamps=sorted(r['timestamp'] for r in rows)
        step={'m5':300,'h1':3600}.get(tf)
        gaps=[(b-a)//step-1 for a,b in zip(stamps,stamps[1:]) if step and b-a>step] if step else []
        streams.append({'provider':provider,'pair':pair,'timeframe':tf,'month':month,
            'count':len(stamps),'first_opened_at':stamps[0] if stamps else None,
            'last_opened_at':stamps[-1] if stamps else None,
            'missing_grid_intervals':sum(gaps) if step else None,
            'gap_segments':len(gaps) if step else None,
            'gap_meaning':'observed_grid_discontinuity_not_verified_market_closure',
            'daily_gap_policy':'not_inferred_from_elapsed_utc_days' if tf=='d1' else None,
            'sources':sorted({r['source'] for r in rows})})
    return {'streams':streams,'boundaries_between_months_checked':False,
            'historical_completeness_verified':False}
