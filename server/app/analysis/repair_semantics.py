"""Compare rejected and repaired plans without executing rejected JSON.

Only explicit ownership edges are recognized. Field names and value types come
from the execution models, rather than a second list of operation parameters.
An unknown layout cannot acquire meaning just because a repair validates.
"""
import copy
import json

from pydantic import TypeAdapter, ValidationError

from app.analysis.operations import (
    AnalysisPlan, Calendar, ContractError, Metric, REGISTRY, Source,
    canonical, predicate_identity, repair_formula_identity, validate_plan,
    without_optional_nulls,
)


class ConflictingOwnership(ContractError):
    pass


def _json(value):
    # JSON identity distinguishes a boolean predicate from a numeric predicate.
    return json.dumps(value, sort_keys=True, allow_nan=False)


def _field_meaning(owner, name, value, path):
    adapter = TypeAdapter(owner.model_fields[name].annotation)
    try:
        typed = adapter.validate_python(value, strict=True)
    except ValidationError as error:
        message = error.errors(include_input=False)[0]['msg']
        raise ContractError(path, 'cannot establish field ownership: ' + message) from None
    result = without_optional_nulls(adapter.dump_python(typed, by_alias=True))
    if name in {'filters', 'eligibility_filters'}:
        result = sorted((predicate_identity(p) for p in result), key=_json)
    if owner is Calendar and name == 'years':
        result = sorted(set(result))
    return result


def _move(child, parent, owner, name, child_path, parent_path):
    meaning = _field_meaning(owner, name, child[name], child_path + '.' + name)
    if name in parent:
        existing = _field_meaning(owner, name, parent[name], parent_path + '.' + name)
        if _json(meaning) != _json(existing):
            raise ConflictingOwnership(child_path + '.' + name,
                                       'conflicting copies of ' + parent_path + '.' + name)
    else:
        parent[name] = copy.deepcopy(child[name])
    del child[name]


def project_ownership(value):
    """A comparison-only projection; execution still requires strict input.

    Calendar parameters misplaced in Metric have one immediate schema owner.
    Chart scope misplaced in a single output has one analysis-wide owner.
    Multi-output chart scopes and arbitrary containers are deliberately not
    promoted: their intended ownership would be ambiguous.
    """
    result = copy.deepcopy(value)
    plan = result.get('analysis_plan') if isinstance(result, dict) else None
    if not isinstance(plan, dict) or not isinstance(plan.get('outputs'), list):
        return result
    # These presentation fields have exactly one schema owner. Relocation is a
    # representation repair; conflicting copies must still reject.
    for name in ('chart_scope','presentation'):
        if name in result:
            if result[name] is None:
                result.pop(name)
            else:
                _move(result,plan,AnalysisPlan,name,'$','$.analysis_plan')
    for i, output in enumerate(plan['outputs']):
        if not isinstance(output, dict):
            continue
        path = f'$.analysis_plan.outputs[{i}]'
        if 'chart_scope' in output:
            if len(plan['outputs']) != 1:
                raise ContractError(path + '.chart_scope',
                                    'ambiguous analysis-wide ownership across multiple outputs')
            _move(output, plan, AnalysisPlan, 'chart_scope', path, '$.analysis_plan')
        parameters = output.get('parameters')
        model = REGISTRY.get(output.get('kind'))
        if model is Calendar and isinstance(parameters, dict):
            metric = parameters.get('metric')
            if isinstance(metric, dict):
                # Do not promote fields Metric itself owns, nor replace Metric
                # with a nested copy of itself. No search through arbitrary JSON.
                owned = model.model_fields.keys() - Metric.model_fields.keys() - {'metric'}
                for name in sorted(metric.keys() & owned):
                    _move(metric, parameters, model, name, path + '.parameters.metric',
                          path + '.parameters')
    return result


def _source(value):
    source = Source.model_validate(value).model_dump(exclude_none=True)
    # The same declared join edge may be written in either direction. Keep table
    # ordering: it can affect resolution of overlapping unqualified columns.
    source['join_keys'] = sorted(
        [sorted([(k['from_table'], k['from_column']),
                 (k['to_table'], k['to_column'])]) for k in source['join_keys']],
        key=_json,
    )
    return source


def _snapshot(value):
    value = copy.deepcopy(value)
    presentation=[{'table':(o.get('parameters',{}).get('output') or {}).get('table',True),'chart':(o.get('parameters',{}).get('output') or {}).get('chart','line')} for o in value['analysis_plan']['outputs']]
    for output in value['analysis_plan']['outputs']:
        parameters = output.get('parameters')
        if not isinstance(parameters, dict):
            continue
        metric = parameters.get('metric')
        if output.get('kind') == 'calendar_aggregate' and isinstance(metric, dict):
            if isinstance(metric.get('expression'), dict):
                metric['expression'] = repair_formula_identity(metric['expression'])
        if output.get('kind') == 'aggregation':
            for measure in parameters.get('derived_measures') or []:
                if isinstance(measure, dict) and isinstance(measure.get('expression'), dict):
                    measure['expression'] = repair_formula_identity(measure['expression'])
    # A legacy model sometimes appended prose fragments to an otherwise fully
    # typed duplicate measure list. Compare all meaningful typed constraints;
    # fragments have no executable or requested meaning and cannot own fields.
    requirements=value.get('request_requirements') or {}
    for spec in requirements.get('outputs',[]):
        if isinstance(spec,dict) and isinstance(spec.get('parameters'),dict):
            spec['measures']=[m for m in (spec.get('measures') or []) if isinstance(m,dict)]
    value = validate_plan(value)
    plan = AnalysisPlan.model_validate(value['analysis_plan']).model_dump(exclude_none=True)
    outputs = []
    for i, output in enumerate(plan['outputs']):
        source = _source(output.get('source') or plan['source'])
        parameters = output['parameters']
        if output['kind'] == 'calendar_aggregate' and parameters.get('source'):
            if _source(parameters['source']) != source:
                raise ConflictingOwnership(f'$.analysis_plan.outputs[{i}].parameters.source',
                                           'conflicting copies of the operation source')
        outputs.append({'id': output['id'], 'kind': output['kind'], 'source': source,
                        'parameters': canonical(output['kind'], parameters)})
    return {'requested_presentation':presentation,'request_requirements': value.get('request_requirements'),
            'context_action': value.get('context_action', 'standalone'),
            'reference_message_id': value.get('reference_message_id'),
            'changed_fields': sorted(set(value.get('changed_fields', []))),
            'analysis_plan': {'source': _source(plan['source']), 'outputs': outputs,
                              'chart_scope': plan['chart_scope'],'presentation':plan.get('presentation',{})}}


def _difference(before, after, path='$'):
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            child = path + '.' + key
            if key not in before or key not in after:
                return child
            difference = _difference(before[key], after[key], child)
            if difference:
                return difference
    elif isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return path
        for i, (a, b) in enumerate(zip(before, after)):
            difference = _difference(a, b, f'{path}[{i}]')
            if difference:
                return difference
    elif _json(before) != _json(after):
        return path
    return None


def compare_typed_repair(original, repaired):
    projected = project_ownership(original)
    try:
        before = _snapshot(projected)
    except ConflictingOwnership:
        raise
    except (ValueError, TypeError, KeyError):
        # Other malformed fields still use the conservative semantic-atom guard.
        # Ownership conflicts above are never swallowed by this fallback.
        return projected, False
    after = _snapshot(repaired)
    difference = _difference(before, after)
    if difference:
        detail = ('population predicates' if any(name in difference for name in ('.filters', '.eligibility_filters'))
                  else 'a requested calculation field or scope')
        raise ContractError(difference,
                            'schema repair changed ' + detail + '; clarify instead')
    return projected, True
