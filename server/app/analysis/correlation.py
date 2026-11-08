"""Validated correlation matrices and explanations grounded in their coefficients."""
import re
import numpy as np
import pandas as pd


def is_correlation_request(question):
    return bool(re.search(r'\b(?:correlations?|pearson|spearman)\b', question, re.I))


def validate_python_correlation(captures, frame, request):
    """Accept a Python matrix only when it agrees with its resolved source data."""
    expected = compute_correlation(frame, request.get('method', 'pearson'), request.get('columns'))
    for captured in reversed(captures):
        if captured.get('columns') != expected['columns'] or captured.get('method') != expected['method']:
            continue
        actual = np.asarray(captured.get('matrix'), dtype=float)
        target = np.asarray(expected['matrix'], dtype=float)
        if (captured.get('source_observation_count') == len(frame) and actual.shape == target.shape
                and np.allclose(actual, target, atol=1e-12, rtol=1e-10, equal_nan=True)):
            return correlation_result(expected)
    raise ValueError('Python did not return the requested correlation matrix for the full resolved source. '
                     'Compute df[requested_columns].corr(method="pearson" or "spearman"); '
                     'a printed table or PNG alone is not a structured correlation result.')


def requested_columns(question, available):
    """Resolve explicitly named measures in question order without guessing synonyms."""
    matches = []
    for column in available:
        match = re.search(r'(?<!\w)' + re.escape(str(column)) + r'(?!\w)', question, re.I)
        if match:
            matches.append((match.start(), column))
    return [column for _, column in sorted(matches)]


def compute_correlation(df, method='pearson', columns=None):
    if method not in ('pearson', 'spearman'):
        raise ValueError('Correlation method must be pearson or spearman.')
    if columns is None:
        columns = [column for column in df.select_dtypes(include=['number']).columns
                   if not re.search(r'(?:^id$|id$|_id$)', str(column), re.I)]
    if not isinstance(columns, list) or len(columns) < 2 or len(set(columns)) != len(columns):
        raise ValueError('Correlation requires at least two distinct numeric column names in columns.')
    for column in columns:
        if column not in df.columns or not pd.api.types.is_numeric_dtype(df[column]):
            raise ValueError(f'Unknown or nonnumeric correlation column {column!r}.')
    numeric = df[columns].replace([np.inf, -np.inf], np.nan)
    if len(numeric) < 2:
        raise ValueError('Correlation requires at least two source observations.')
    matrix = numeric.corr(method=method).astype(object)
    matrix = matrix.where(pd.notna(matrix), None)
    valid = numeric.notna().astype('int64')
    return {'columns': columns, 'matrix': matrix.values.tolist(), 'method': method,
            'source_observation_count': len(df),
            'pair_observation_counts': (valid.T @ valid).values.tolist(),
            'missing_value_policy': 'Pairwise complete finite observations; undefined coefficients remain null.'}


def correlation_result(correlation):
    columns = correlation['columns']
    label = 'Measure'
    while label in columns:
        label = '_' + label
    return {'analysis_kind': 'correlation', 'correlation': correlation,
            'source_observation_count': correlation['source_observation_count'],
            'columns': [label, *columns],
            'data': [{label: name, **dict(zip(columns, values))}
                     for name, values in zip(columns, correlation['matrix'])],
            'row_count': len(columns),
            'data_types': {label: 'category', **{column: 'float' for column in columns}}}


def explanation(result):
    corr = result['correlation']
    columns = corr['columns']
    rows = ['| Measure | ' + ' | '.join(columns) + ' |', '|---|' + '---:|' * len(columns)]
    for name, values in zip(columns, corr['matrix']):
        rows.append('| ' + name + ' | ' + ' | '.join('undefined' if value is None else f'{value:.4f}' for value in values) + ' |')
    interpretation = ('Pearson correlation measures linear association. Near-zero coefficients indicate little linear association; '
                      'they do not establish statistical independence or rule out nonlinear relationships.'
                      if corr['method'] == 'pearson' else
                      'Spearman correlation measures monotonic rank association. Near-zero coefficients do not establish statistical independence or rule out nonmonotonic relationships.')
    return (f"{corr['method'].title()} correlation matrix for {', '.join(columns)}. "
            f"Source observations: {corr['source_observation_count']:,}; the result has {len(columns)} matrix rows.\n\n"
            + '\n'.join(rows) + '\n\n' + interpretation
            + '\n\nCoefficients use pairwise complete finite observations; undefined correlations remain blank in Table and Chart. '
              'Open result shows the same matrix in Table and as a heatmap in Chart.')
