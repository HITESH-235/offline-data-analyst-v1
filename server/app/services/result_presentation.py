"""Presentation only: retain all verified tables; expose detail when it adds value."""


def summary_table(table):
    result=table['result'];kind=result.get('analysis_kind',table.get('tool'))
    params=table.get('parameters') or {}
    # A grouped observation, trend, matrix or entity comparison is meaningful
    # detail even when filtering leaves only one row. Row count alone is insufficient.
    return (kind=='aggregation' and not params.get('group_by') and len(result.get('data',[]))==1
            and bool(result.get('columns'))
            and all(value is None or isinstance(value,(str,int,float,bool)) for value in result['data'][0].values()))


def disposition(tables,charts=(),*,table_requested=False):
    scalar_values=sum(len(t['result'].get('columns',[])) for t in tables if summary_table(t))
    compact=bool(tables) and all(summary_table(t) for t in tables) and scalar_values<=6
    table_ids=[t['id'] for t in tables if table_requested or not compact]
    return {'has_detail':bool(table_ids or charts),'table_ids':table_ids,
            'chart_ids':[c['id'] for c in charts],'table_requested':table_requested}
