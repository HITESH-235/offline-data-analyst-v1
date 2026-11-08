"""Deterministic calendar-month revenue from a resolved line-item dataframe."""
import re
import numpy as np
import pandas as pd
from app.analysis.filtering import filter_data, parse_dates


def requested_year(question):
    # A bounded, explicit request shape: complex comparisons still use the agent.
    match = re.fullmatch(r'\s*(?:(?:please\s+)?(?:show|calculate|compute|give|get)\s+(?:me\s+)?)?monthly\s+revenue\s+(?:for\s+|in\s+)?(?:the\s+)?(?:year\s+)?(\d{4})\s*[.!?]?\s*', question, re.I)
    return int(match[1]) if match else None


def calculate_monthly_revenue(df, parameters):
    fields = {'year','date_column','unit_price_column','quantity_column','discount_column'}
    if not isinstance(parameters,dict) or set(parameters) != fields:
        raise ValueError('monthly_revenue requires year, date_column, unit_price_column, quantity_column, and discount_column separately.')
    year = parameters['year']
    if not isinstance(year,int) or isinstance(year,bool) or not 1678 <= year <= 2260:
        raise ValueError('year must be an integer between 1678 and 2260.')
    for key in fields - {'year'}:
        if not isinstance(parameters[key], str) or parameters[key] not in df.columns:
            raise ValueError(f'Unknown {key}: {parameters[key]!r}. Available columns: {list(df.columns)}')
    df = df.reset_index(drop=True)
    date_column = parameters['date_column']
    dates = parse_dates(df[date_column],date_column)
    if dates.isna().any():
        raise ValueError('Monthly revenue cannot silently discard missing OrderDate values.')
    filters = [{'column':date_column,'operator':'>=','value':f'{year}-01-01','value_type':'date'},
               {'column':date_column,'operator':'<','value':f'{year+1}-01-01','value_type':'date'}]
    selected = filter_data(df,filters)
    measures = {}
    for key in ('unit_price_column','quantity_column','discount_column'):
        column = parameters[key]
        try: values = pd.to_numeric(selected[column],errors='raise')
        except (TypeError,ValueError): raise ValueError(f'Revenue column {column!r} must contain numeric values.') from None
        if not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(f'Revenue column {column!r} contains missing or non-finite values.')
        measures[key] = values
    discount = measures['discount_column']
    if not discount.between(0,1).all():
        raise ValueError('Discount must be a fraction between 0 and 1.')
    values = measures['unit_price_column'] * measures['quantity_column'] * (1-discount)
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError('Calculated revenue contains non-finite values.')
    monthly = pd.DataFrame({'Month':dates.loc[selected.index].dt.strftime('%Y-%m'), 'Revenue':values}).groupby('Month',as_index=False,sort=True)['Revenue'].sum()
    return {'analysis_kind':'monthly_revenue', 'columns':['Month','Revenue'], 'data':monthly.to_dict(orient='records'),
            'row_count':len(monthly), 'data_types':{'Month':'date','Revenue':'float'},
            'visualization_blueprint':{'chart_type':'line','x':'Month','y':'Revenue','title':f'Monthly revenue for {year}'},
            'verification':{'year':year,'input_row_count':len(df),'matched_row_count':len(selected),
                            'date_min':dates.min().isoformat() if len(dates) else None,
                            'date_max':dates.max().isoformat() if len(dates) else None,
                            'filters':filters,'formula':'UnitPrice * Quantity * (1 - Discount)',
                            'total_revenue':float(monthly['Revenue'].sum())}}


def explanation(result):
    facts = result['verification']
    if not facts['matched_row_count']:
        return f"The validated date filter found no order-detail rows for {facts['year']}. Full input date range: {facts['date_min']} to {facts['date_max']}. No monthly revenue was calculated."
    return (f"Calculated monthly revenue for {facts['year']} from {facts['matched_row_count']:,} joined order-detail rows, "
            f"using UnitPrice × Quantity × (1 − Discount). The result contains {result['row_count']} calendar months in chronological order. "
            f"Total revenue: {facts['total_revenue']:,.2f}. Open result to inspect the monthly table and line chart.")
