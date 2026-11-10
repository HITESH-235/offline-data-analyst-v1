"""Explicit typed field aliases shared by input normalization and change paths."""
def ownership(properties):
    owners={}
    for canonical,metadata in properties.items():
        for name in [canonical,*metadata.get('input_aliases',[])]:owners.setdefault(name,set()).add(canonical)
    return owners


def normalize_fields(model,value):
    if not isinstance(value,dict):return value
    fields={(field.alias or name):(field.json_schema_extra or {}) for name,field in model.model_fields.items()}
    owners=ownership(fields);result={}
    for name,item in value.items():
        candidates=owners.get(name,{name})
        if len(candidates)!=1:raise ValueError('ambiguous field '+repr(name)+'; canonical fields: '+', '.join(sorted(candidates)))
        canonical=next(iter(candidates))
        if canonical in result:raise ValueError('conflicting declarations; use only canonical field '+canonical)
        result[canonical]=item
    return result
