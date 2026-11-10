"""Legacy aggregate reader and internal lowering; neither interprets language."""
import copy
import re
import hashlib


def from_legacy(value):
    from app.analysis.operations import ContractError
    p=copy.deepcopy(value)
    if 'measures' in p:
        if any(k in p for k in ('aggregations','output_names','transforms')):raise ValueError('provide measures only; competing aggregate representations are forbidden')
        return p
    columns=p.pop('aggregations',{})
    if not isinstance(columns,dict):raise ValueError('aggregations must be a column-to-operation object')
    names=p.pop('output_names',{}) or {};transforms=p.pop('transforms',[]) or []
    aliases={}
    for column,op in columns.items():
        op={'avg':'mean','average':'mean','nunique':'count_distinct'}.get(op,op);columns[column]=op
        for name in (column,column+'_'+op,op+'_'+column,op):aliases.setdefault(name,set()).add(column)
    def owner(name):
        if name in columns:return name
        candidates=aliases.get(name,set())
        if len(candidates)!=1:raise ValueError('ambiguous or unknown aggregate reference '+repr(name)+'; use an explicit input column or stable measure id')
        return next(iter(candidates))
    labels={}
    for name,label in names.items():
        col=owner(name)
        if col in labels and labels[col]!=label:raise ValueError('conflicting aggregate labels for '+col)
        labels[col]=label
    converted={}
    for transform in transforms:
        col=owner(transform['column'])
        if col in converted:raise ValueError('duplicate aggregate conversion for '+col)
        if set(transform)-{'column','divide_by','as','unit'}:raise ValueError('unknown aggregate conversion fields')
        converted[col]=transform;labels[col]=transform['as']
    measures=[]
    from app.analysis.result_operations import human
    for column,op in columns.items():
        default=human(re.sub(r'[_ .]?id$','',column,flags=re.I))+(' Distinct Count' if op=='count_distinct' else ' Count') if op in {'count','count_distinct'} else column
        identity=column if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',column) else 'measure_'+hashlib.sha256(column.encode()).hexdigest()[:12]
        m={'id':identity,'column':column,'operation':op,'label':labels.get(column,default)}
        t=converted.get(column)
        if t:m.update({k:t[k] for k in ('divide_by','unit') if k in t})
        measures.append(m)
    if p.get('sort_by') is not None:
        sort=p['sort_by'];matches={m['id'] for m in measures if sort in {m['id'],m['column'],m['label'],m['operation'],m['operation']+'_'+m['column'],m['column']+'_'+m['operation']}}
        if sort not in (p.get('group_by') or []) and sort not in [d['name'] for d in p.get('derived_measures') or []]:
            if len(matches)!=1:raise ValueError('ambiguous or unknown aggregate sort reference '+repr(sort))
            p['sort_by']=next(iter(matches))
    p['measures']=measures
    return p


def kernel(parameters):
    if 'measures' not in parameters:return copy.deepcopy(parameters)
    p=copy.deepcopy(parameters);measures=p.pop('measures')
    p['aggregations']={m['column']:m['operation'] for m in measures}
    p['output_names']={m['column']:m['label'] for m in measures}
    p['transforms']=[{'column':m['column'],'divide_by':m['divide_by'],'as':m['label'],**({'unit':m['unit']} if m.get('unit') else {})} for m in measures if m.get('divide_by') is not None]
    labels={m['id']:m['label'] for m in measures}
    if p.get('sort_by') in labels:p['sort_by']=labels[p['sort_by']]
    def expression(node):
        if 'column' in node:return {'column':labels.get(node['column'],node['column'])}
        return {**node,**({'args':[expression(arg) for arg in node['args']]} if 'args' in node else {})}
    for derived in p.get('derived_measures',[]):derived['expression']=expression(derived['expression'])
    return p
