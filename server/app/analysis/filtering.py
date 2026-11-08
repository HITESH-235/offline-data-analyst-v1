"""Validated filters: no predicate may be ignored or silently coerced away."""
import math
import re
import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype

OPERATORS = {'==', '!=', '>', '<', '>=', '<=', 'contains', 'in'}
EXAMPLE = 'Expected {"filters":[{"column":"OrderDate","operator":">=","value":"2022-01-01"},{"column":"OrderDate","operator":"<","value":"2023-01-01"}]} for year 2022.'
ISO_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}(?:[T ].*)?$')


def parse_dates(series, column):
    """Parse all non-null dates, including mixed ISO dates/timestamps, or fail."""
    values = series.dropna()
    if not is_datetime64_any_dtype(series) and not values.map(lambda value: isinstance(value, str) and bool(ISO_DATE.fullmatch(value))).all():
        raise ValueError(f"Column {column!r} contains non-ISO or invalid dates. No dates were silently discarded.")
    try:
        return pd.to_datetime(series, format='mixed', errors='raise', utc=True)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"Cannot parse dates in {column!r}: {error}. No dates were silently discarded.") from None


def _predicate(df, condition):
    if isinstance(condition,dict) and 'value_column' in condition:
        return column_comparison(df,condition)
    if not isinstance(condition, dict) or not {'column', 'operator', 'value'} <= condition.keys() or set(condition) - {'column','operator','value','value_type'}:
        raise ValueError(f'Each filter requires column, operator, and value; optional value_type is supported. {EXAMPLE}')
    column, operator, value = condition['column'], condition['operator'], condition['value']
    if not isinstance(column, str) or column not in df.columns:
        raise ValueError(f'Unknown filter column {column!r}. Available columns: {list(df.columns)}. {EXAMPLE}')
    if not isinstance(operator, str) or operator not in OPERATORS:
        raise ValueError(f'Unsupported filter operator {operator!r}. Supported: {sorted(OPERATORS)}. {EXAMPLE}')
    kind = condition.get('value_type')
    if kind not in (None, 'date', 'number', 'string', 'boolean'):
        raise ValueError(f'Unsupported value_type {kind!r}. Use date, number, string, or boolean.')
    if operator == 'in' and not isinstance(value, list):
        raise ValueError(f"Filter 'in' requires a list of values. {EXAMPLE}")
    series = df[column]
    values = value if operator == 'in' else [value]
    if any(isinstance(item, (dict, list)) for item in values):
        raise ValueError(f'Filter values must be scalars. {EXAMPLE}')
    if value is None and operator in ('==', '!='):
        return series.isna() if operator == '==' else series.notna()
    date_filter = kind == 'date' or is_datetime64_any_dtype(series) or (operator != 'contains' and bool(values) and all(isinstance(item, str) and ISO_DATE.fullmatch(item) for item in values))
    if date_filter:
        if isinstance(value,str) and value in df.columns:
            raise ValueError(f'{value!r} names a column, not an ISO date literal. Use value_column instead of value, with value_type="date" and date_part="date" for calendar-date comparison. Use comparison_summary for numerator, denominator and percentage.')
        if operator == 'contains':
            raise ValueError('contains is not a date comparison.')
        series = parse_dates(series, column)
        try:
            converted = pd.to_datetime(values, format='mixed', errors='raise', utc=True)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f'Invalid date filter values for {column!r}. {EXAMPLE}') from None
        if converted.isna().any():
            raise ValueError('Date comparison values cannot be null.')
        value = list(converted) if operator == 'in' else converted[0]
    elif is_bool_dtype(series) or kind == 'boolean':
        if not is_bool_dtype(series) and not series.dropna().map(lambda item: isinstance(item,bool)).all():
            raise ValueError(f'Column {column!r} is not boolean.')
        if not all(isinstance(item, bool) for item in values) or operator not in ('==','!=','in'):
            raise ValueError('Boolean filters require boolean values and ==, !=, or in.')
    elif is_numeric_dtype(series) or kind == 'number':
        if not is_numeric_dtype(series):
            raise ValueError(f'Column {column!r} is not numeric.')
        if operator == 'contains' or not all(isinstance(item,(int,float)) and not isinstance(item,bool) and math.isfinite(item) for item in values):
            raise ValueError(f'Numeric filter on {column!r} requires finite JSON numbers, not expressions or text.')
    elif operator == 'contains':
        if not isinstance(value, str):
            raise ValueError('contains requires a string value.')
        return series.astype('string').str.contains(value, case=False, regex=False, na=False)
    elif operator not in ('==', '!=', 'in'):
        raise ValueError(f'Ordered text comparison on {column!r} is unsupported. For dates, use ISO date values and value_type="date".')
    elif not all(isinstance(item,str) for item in values):
        raise ValueError(f'Text filter on {column!r} requires string values.')
    try:
        if operator == 'in': mask = series.isin(value)
        elif operator == '==': mask = series == value
        elif operator == '!=': mask = series != value
        elif operator == '>': mask = series > value
        elif operator == '<': mask = series < value
        elif operator == '>=': mask = series >= value
        else: mask = series <= value
        return (mask & series.notna()).fillna(False)
    except (TypeError, ValueError) as error:
        raise ValueError(f'Cannot apply filter on {column!r}: {error}. {EXAMPLE}') from None


def column_comparison(df,condition):
    allowed={'column','operator','value_column','value_type','date_part'}
    if set(condition)-allowed or not {'column','operator','value_column'}<=set(condition):
        raise ValueError('Column comparisons require column/operator/value_column, optional value_type/date_part; never supply both value and value_column.')
    left,right=condition['column'],condition['value_column'];op=condition['operator']
    if left not in df or right not in df:raise ValueError(f'Unknown comparison column. Available: {list(df.columns)}')
    if op not in {'>','<','>=','<=','==','!='}:raise ValueError('Column comparisons support >, <, >=, <=, ==, !=.')
    a,b=df[left],df[right]
    kind=condition.get('value_type');part=condition.get('date_part')
    if part not in (None,'date'):raise ValueError('date_part must be date or omitted.')
    if kind=='date':
        a,b=parse_dates(a,left),parse_dates(b,right)
        if part=='date':a,b=a.dt.normalize(),b.dt.normalize()
    elif kind in (None,'number') and is_numeric_dtype(a) and is_numeric_dtype(b):
        if part:raise ValueError('date_part requires value_type=date.')
    else:raise ValueError('Column references require numeric columns or explicit value_type=date. Strings remain literal values unless value_column is supplied.')
    mask={'>':lambda:a>b,'<':lambda:a<b,'>=':lambda:a>=b,'<=':lambda:a<=b,'==':lambda:a==b,'!=':lambda:a!=b}[op]()
    return (mask & a.notna() & b.notna()).fillna(False)


def filter_data(df, filters):
    if not isinstance(filters, list) or not filters:
        raise ValueError(f'filters must be a non-empty list of predicates. {EXAMPLE}')
    # Validate every predicate against the full schema, even if another matches no rows.
    masks = [_predicate(df, condition) for condition in filters]
    mask = pd.Series(True, index=df.index)
    for predicate in masks:
        mask &= predicate
    return df.loc[mask].copy()
