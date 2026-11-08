"""Validated calendar aggregation of a structured metric, independent of model prose."""
import copy
import numpy as np
import pandas as pd
from app.analysis.filtering import parse_dates,filter_data


def evaluate(node,df,depth=0):
    if not isinstance(node,dict) or depth>6:raise ValueError('Invalid metric expression.')
    if set(node)=={'column'}:
        name=node['column']
        if name not in df:raise ValueError(f'Unknown metric column {name!r}.')
        values=pd.to_numeric(df[name],errors='raise')
    elif set(node)=={'value'} and isinstance(node['value'],(int,float)) and not isinstance(node['value'],bool):values=node['value']
    elif (set(node)=={'op','args'} and node['op'] in {'multiply','subtract','add'}
          and isinstance(node['args'],list) and 2<=len(node['args'])<=8
          and (node['op']!='subtract' or len(node['args'])==2)):
        values=evaluate(node['args'][0],df,depth+1)
        for arg in node['args'][1:]:
            right=evaluate(arg,df,depth+1)
            values=values*right if node['op']=='multiply' else values-right if node['op']=='subtract' else values+right
    else:raise ValueError('Unsupported metric expression; use column/value leaves and multiply/subtract/add operators.')
    if not np.isfinite(np.asarray(values,dtype=float)).all():raise ValueError('Metric contains missing or non-finite values.')
    return values


def calculate(df,state):
    state=copy.deepcopy(state)
    grain=state.get('grain');years=state.get('years');metric=state.get('metric',{})
    if grain not in {'month','quarter','year'}:raise ValueError('Grouping must be month, quarter, or year.')
    if not isinstance(years,list) or not years or len(years)>10 or any(type(y)!=int or not 1678<=y<=2260 for y in years):raise ValueError('Provide one to ten valid calendar years.')
    years=sorted(set(years));state['years']=years
    if not isinstance(metric.get('name'),str) or not metric['name'] or metric.get('aggregation') not in {'sum','count'}:raise ValueError('Metric requires a name and sum/count aggregation.')
    date=state.get('date_column')
    if date not in df:raise ValueError(f'Unknown date column {date!r}.')
    base=filter_data(df,state['filters']) if state.get('filters') else df.copy()
    dates=parse_dates(base[date],date)
    if dates.isna().any():raise ValueError('Calendar analysis cannot discard missing dates.')
    base=base.reset_index(drop=True);dates=dates.reset_index(drop=True)
    in_scope=dates.dt.year.isin(years)
    base=base.loc[in_scope].reset_index(drop=True)
    dates=dates.loc[in_scope].reset_index(drop=True)
    values=evaluate(metric.get('expression'),base) if metric['aggregation']=='sum' else pd.Series(1.,index=base.index)
    if np.isscalar(values):values=pd.Series(values,index=base.index)
    observations=pd.DataFrame({'Year':dates.dt.year,'Period':dates.dt.month if grain=='month' else dates.dt.quarter if grain=='quarter' else 1,'Value':values})
    observations=observations[observations.Year.isin(years)]
    grouped=observations.groupby(['Year','Period']).Value.sum()
    totals={str(year):float(observations.loc[observations.Year==year,'Value'].sum()) for year in years}
    compare=state.get('compare',False)
    if type(compare)!=bool:raise ValueError('compare must be boolean.')
    name=metric['name'];label={'month':'Month','quarter':'Quarter','year':'Year'}[grain]
    count={'month':12,'quarter':4,'year':1}[grain]
    data=[]
    if compare:
        for period in range(1,count+1):
            row={label:f'Q{period}' if grain=='quarter' else f'{period:02d}' if grain=='month' else 'Annual'}
            row.update({f'{name} {year}':float(grouped.get((year,period),0.)) for year in years});data.append(row)
        measures=[f'{name} {year}' for year in years]
    else:
        for year in years:
            for period in range(1,count+1):
                key=f'{year}-Q{period}' if grain=='quarter' else f'{year}-{period:02d}' if grain=='month' else str(year)
                data.append({label:key,name:float(grouped.get((year,period),0.))})
        measures=[name]
    return {'analysis_kind':'calendar_aggregate','columns':[label,*measures],'data':data,'row_count':len(data),
            'analysis_context':state,'source_observation_count':len(observations),
            'units':{m:metric['unit'] for m in measures} if metric.get('unit') else {},
            'verification':{'annual_totals':totals,'matched_row_count':len(observations),'empty_period_policy':'Empty calendar periods are included with zero sum/count.'},
            'calendar_chart':{'x':label,'series':measures,'grain':grain},
            'data_types':{label:'category',**{m:'float' for m in measures}}}


def expression_text(node):
    if 'column' in node:return node['column']
    if 'value' in node:return str(node['value'])
    symbol={'multiply':'×','subtract':'−','add':'+'}[node['op']]
    return '('+f' {symbol} '.join(expression_text(arg) for arg in node['args'])+')'


def explanation(result):
    state=result['analysis_context'];metric=state['metric']
    formula='row count' if metric['aggregation']=='count' else expression_text(metric['expression'])
    columns=result['columns'];rows=['| '+' | '.join(columns)+' |','|'+'---|'*len(columns)]
    for row in result['data']:rows.append('| '+' | '.join(f'{row[c]:,.2f}' if isinstance(row[c],float) else str(row[c]) for c in columns)+' |')
    totals='; '.join(f'{year}: {value:,.2f}' for year,value in result['verification']['annual_totals'].items())
    return (f"{metric['name']} by calendar {state['grain']} for {', '.join(map(str,state['years']))}. "
            f"Calculation: {metric['aggregation']} of {formula}. Source observations: {result['source_observation_count']:,}.\n\n"+'\n'.join(rows)+
            f'\n\nAnnual totals: {totals}. Empty periods have zero sum/count. Open result shows these same values in Table and Chart.')
