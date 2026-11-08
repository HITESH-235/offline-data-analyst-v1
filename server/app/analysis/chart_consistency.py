"""Bind supported chart requests to the population actually plotted."""
import hashlib
import re
import numpy as np
import pandas as pd


def population_summary(values):
    array = np.asarray(values, dtype=float).reshape(-1)
    if not np.isfinite(array).all():
        raise ValueError('Chart observations contain missing or non-finite values.')
    canonical = np.sort(np.round(array, 8)).astype('<f8')
    return {'count':len(array), 'fingerprint':hashlib.sha256(canonical.tobytes()).hexdigest(),
            'minimum':float(array.min()) if len(array) else None,
            'maximum':float(array.max()) if len(array) else None,
            'mean':float(array.mean()) if len(array) else None,
            'median':float(np.median(array)) if len(array) else None,
            'standard_deviation':float(array.std(ddof=1)) if len(array)>1 else None,
            'total':float(array.sum())}


def wants_order_total_histogram(question):
    return bool(re.fullmatch(r'\s*(?:(?:please\s+)?(?:show|plot|create|make|give)\s+(?:me\s+)?)?(?:a\s+)?histogram\s+of\s+(?:individual\s+)?order\s+totals\s+after\s+discounts?\s*[.!?]?\s*', question,re.I))


def order_total_expectation(frame):
    if frame.empty:
        raise ValueError('No observations are available for an order-total histogram.')
    required=['OrderID','UnitPrice','Quantity','Discount']
    if any(column not in frame.columns for column in required):
        raise ValueError(f'Order-total histograms require these resolved columns: {required}.')
    if frame['OrderID'].isna().any():
        raise ValueError('Cannot aggregate orders with missing OrderID values.')
    price,quantity,discount=[pd.to_numeric(frame[column],errors='raise') for column in required[1:]]
    if not np.isfinite(np.column_stack([price,quantity,discount])).all() or not discount.between(0,1).all():
        raise ValueError('Order totals require finite price/quantity values and fractional discounts between 0 and 1.')
    totals=pd.DataFrame({'OrderID':frame['OrderID'],'Total':price*quantity*(1-discount)}).groupby('OrderID',sort=True)['Total'].sum()
    return {**population_summary(totals),'population':'orders','input_line_count':len(frame),
            'group_by':['OrderID'],'formula':'SUM(UnitPrice * Quantity * (1 - Discount)) per OrderID'}


def validate_captures(captures, expectation):
    if not expectation:
        return
    if not captures:
        raise ValueError('No histogram was captured for the requested order-total distribution.')
    for capture in captures:
        observations=capture.get('observations') or []
        if capture.get('status') != 'ready' or not observations:
            raise ValueError('The captured chart has no verifiable histogram observations. Use Axes.hist/plt.hist or a Plotly histogram of the actual order-total values.')
        for actual in observations:
            if actual.get('weighted') or actual.get('fingerprint') != expectation['fingerprint'] or actual.get('count') != expectation['count']:
                raise ValueError(f"Chart population mismatch: plotted {actual.get('count','unknown')} observations, but the request requires {expectation['count']} aggregated orders from {expectation['input_line_count']} line items. First group net line amounts by OrderID, then plot those totals. Renaming a line-item chart is not sufficient.")
        capture['population']={**expectation,'verified':True}


def order_total_explanation(expectation):
    rows=[('Number of orders',str(expectation['count'])),('Minimum order total',f"{expectation['minimum']:,.2f}"),
          ('Maximum order total',f"{expectation['maximum']:,.2f}"),('Mean',f"{expectation['mean']:,.2f}"),
          ('Median',f"{expectation['median']:,.2f}"),('Standard deviation',f"{expectation['standard_deviation']:,.2f}" if expectation['standard_deviation'] is not None else 'N/A'),
          ('Sum of order totals',f"{expectation['total']:,.2f}")]
    return (f"Histogram of individual order totals after discounts. Each observation is one OrderID, calculated by summing UnitPrice × Quantity × (1 − Discount) across its line items. "
            f"The displayed chart population was checked against all {expectation['count']:,} order totals from {expectation['input_line_count']:,} line items.\n\n"
            '| Metric | Value |\n|---|---:|\n'+'\n'.join(f'| {name} | {value} |' for name,value in rows))
