"""Selected descriptive statistics. Nonmissing counts and undefined values are explicit."""
import pandas as pd

DEFAULT_STATISTICS=('mean','std','min','max','median','q25','q75','iqr')
LEGACY_STATISTICS=(*DEFAULT_STATISTICS,'outliers_count','outliers_percentage','outlier_values')
SUPPORTED={*DEFAULT_STATISTICS,'count','outliers_count','outliers_percentage','outlier_values'}

def compute_statistics(df,columns,statistics=None):
    selected=list(DEFAULT_STATISTICS if statistics is None else statistics)
    if not selected or set(selected)-SUPPORTED:raise ValueError('Unsupported or empty statistic selection')
    result={}
    for column in columns:
        if column not in df:raise ValueError('Unknown statistics column '+column)
        raw=df[column]
        if raw.notna().any() and not pd.api.types.is_numeric_dtype(raw):raise ValueError('Statistics requires numeric columns: '+column)
        series=raw.dropna();n=len(series);values={}
        for name in selected:
            if name=='count':values[name]=n
            elif name in {'mean','median','min','max','std'}:values[name]=float(getattr(series,name)()) if n and (name!='std' or n>1) else None
            elif name in {'q25','q75'}:values[name]=float(series.quantile(.25 if name=='q25' else .75)) if n else None
        if set(selected)&{'iqr','outliers_count','outliers_percentage','outlier_values'}:
            q25,q75=(float(series.quantile(q)) for q in (.25,.75)) if n else (None,None)
            iqr=q75-q25 if n else None
            outliers=series[(series<q25-1.5*iqr)|(series>q75+1.5*iqr)] if n else series
            if 'iqr' in selected:values['iqr']=iqr
            if 'outliers_count' in selected:values['outliers_count']=len(outliers)
            if 'outliers_percentage' in selected:values['outliers_percentage']=100.*len(outliers)/n if n else None
            if 'outlier_values' in selected:values['outlier_values']=[float(v) for v in outliers]
        result[column]={name:values[name] for name in selected}
    return result

def verifies_selection(parameters,result):
    selected=parameters.get('statistics')
    if not selected:return False
    stats=result.get('statistics',{})
    if set(stats)!=set(parameters['columns']):return False
    if any(set(stats[column])!=set(selected) for column in parameters['columns']):return False
    if parameters.get('return_table'):
        metrics=list(selected)
        if result.get('columns')!=['column',*metrics] or len(result.get('data',[]))!=len(parameters['columns']):return False
        for row,column in zip(result['data'],parameters['columns']):
            if row.get('column')!=column or any(m not in row or row[m]!=stats[column][m] for m in metrics):return False
    return True
