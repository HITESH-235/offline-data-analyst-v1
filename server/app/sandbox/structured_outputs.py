"""Validate explicit Python table exports against canonical calculation plans."""
import numpy as np
import pandas as pd
from app.analysis.operations import execute
from app.services.analysis_package import validate_table


def verify_exports(exports,frame):
    if not isinstance(exports,list):raise ValueError('Python table exports must be a list.')
    verified=[];seen=set()
    for export in exports:
        if not isinstance(export,dict) or set(export)!={'id','result','plan'}:raise ValueError('Invalid Python table export contract.')
        if not isinstance(export['id'],str) or not export['id'] or export['id'] in seen:raise ValueError('Python output IDs must be distinct nonempty names.')
        seen.add(export['id'])
        plan=export['plan']
        if not isinstance(plan,dict) or set(plan)!={'tool','parameters'} or plan['tool'] not in {'aggregation','comparison_summary','correlation','monthly_revenue'}:
            raise ValueError('Python output requires a supported canonical calculation plan.')
        tool=plan['tool'];p=plan['parameters']
        expected=execute(tool,p,frame)
        actual=export['result'];validate_table(actual)
        if actual['columns']!=expected['columns'] or len(actual['data'])!=len(expected['data']):raise ValueError('Python table shape differs from its declared calculation.')
        for left,right in zip(actual['data'],expected['data']):
            for col in expected['columns']:
                a,b=left[col],right[col]
                if a is None or b is None:
                    if a is not None or b is not None:raise ValueError('Python missing values differ from canonical output.')
                elif isinstance(b,(int,float)):
                    if not isinstance(a,(int,float)) or not np.isclose(a,b,rtol=1e-10,atol=1e-8):raise ValueError('Python numeric values differ from canonical output.')
                elif a!=b:raise ValueError('Python labels differ from canonical output.')
        verified.append({'id':export['id'],'tool':tool,'parameters':p,'result':expected})
    return verified
