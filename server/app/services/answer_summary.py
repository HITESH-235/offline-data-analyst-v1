"""Deterministic chat explanations from verified structured outputs only.

No interpretation model call, causal guesses, or Markdown preview tables.
The full structured output remains authoritative in Open result.
"""
import re


def number(value):
    if value is None:return 'undefined'
    if isinstance(value,float):return f'{value:,.6f}'.rstrip('0').rstrip('.')
    return f'{value:,}' if isinstance(value,int) else str(value)


def _md(value):
    """Keep data labels literal inside Markdown formatting."""
    return re.sub(r'([\\`*_{}\[\]()#+!|<>])',r'\\\1',str(value)).replace('\n',' ')


def comparison_summary(result, *, detail_link=True):
    audit=result['comparison_audit'];p=audit['parameters'];groups=p.get('group_by',[])
    label=p.get('matched_label','Matched')
    if groups:
        formula=audit['percentage_formula'];denominator=formula['denominator'];numerator=formula['numerator']
        n=sum(row[denominator] for row in result['data']);count=sum(row[numerator] for row in result['data'])
        percentage=next(c for c,u in result['units'].items() if u=='%')
        ranked=sorted((row for row in result['data'] if row[percentage] is not None),key=lambda r:r[percentage],reverse=not p.get('ascending',False))
        missing=sum(row['Missing Actual Date'] for row in result['data'])
        missing_comparison=sum(row['Missing '+p.get('comparison_label','Comparison')+' Date'] for row in result['data'])
    else:
        n=audit['comparable_count'];count=audit['matched_count'];ranked=[]
        missing=audit['missing_actual_count'];missing_comparison=audit['missing_comparison_count']
    noun='orders' if p.get('count_label')=='Orders' else 'observations'
    value='date' if p.get('value_type')=='date' else 'value'
    comparison=p.get('comparison_label','comparison').lower()
    actual_name='delivery date' if value=='date' and 'deliver' in p['column'].lower() else 'actual '+value
    comparison_name=comparison+(' delivery date' if value=='date' and 'deliver' in p['value_column'].lower() else ' '+value)
    singular=noun[:-1]
    if n:
        answer=('was late' if count==1 else 'were late') if label.casefold()=='late' else 'matched the comparison condition'
        parts=[f'**Overall {_md(label.lower())} rate: {100*count/n:.6f}%**',
               f'**{count:,} of {n:,}** comparable {singular if n==1 else noun} {answer}.']
    else:
        parts=[f'**The {_md(label.lower())} rate is undefined.**',
               f'No {noun} had both {value}s available for comparison.']
    if ranked:
        heading=f"{'Lowest' if p.get('ascending',False) else 'Highest'} {_md(label.lower())} rates"
        lines=[f"- **{_md(', '.join(str(row[g]) if row[g] is not None else '(missing group)' for g in groups))}:** {row[percentage]:.6f}%" for row in ranked[:3]]
        parts.append('**'+heading+'**\n\n'+'\n'.join(lines))
    notes=[]
    if audit.get('filtered_count',0):
        if missing:
            notes.append(f'**{missing:,} {singular if missing==1 else noun}** {"is" if missing==1 else "are"} missing a recorded {_md(actual_name)} and {"is" if missing==1 else "are"} excluded from the rate.')
        else:notes.append(f'No {_md(actual_name)}s are missing in the selected population.')
        if missing_comparison:
            notes.append(f'**{missing_comparison:,} {singular if missing_comparison==1 else noun}** with a recorded {_md(actual_name)} {"is" if missing_comparison==1 else "are"} missing the {_md(comparison_name)} and {"is" if missing_comparison==1 else "are"} also excluded.')
        else:notes.append(f'No {_md(comparison_name)}s are missing among {noun} with a recorded {_md(actual_name)}.')
    if p.get('date_part')=='date':notes.append('Rates use calendar dates; time of day is ignored.')
    if groups:
        undefined=sum(row[percentage] is None for row in result['data'])
        if undefined:notes.append(f'**{undefined:,} {"group" if undefined==1 else "groups"}** {"has" if undefined==1 else "have"} no comparable {noun}. {"Its rate remains undefined and sorts" if undefined==1 else "Their rates remain undefined and sort"} last.')
    if notes:parts.append('**Data notes**\n\n'+'\n'.join('- '+note for note in notes))
    if groups and detail_link:parts.append(f'The full breakdown for **{len(result["data"]):,} groups** is in **Open result**.')
    return '\n\n'.join(parts)


def statistics_summary(result,parameters):
    unit=parameters.get('unit')
    labels={'count':'nonmissing count','min':'minimum','max':'maximum'}
    lines=[]
    for column,values in result.get('statistics',{}).items():
        descriptions=[f"{labels.get(name,name)}: {number(value) if not isinstance(value,list) else (str(value) if not parameters.get('return_table') else str(len(value))+' values in the result table')}" for name,value in values.items()]
        lines.append('- **'+_md(column)+'**'+(' ('+_md(unit)+')' if unit else '')+': '+', '.join(descriptions)+'.')
    return '**Verified statistics**\n\n'+'\n'.join(lines)+'\n\nStatistics use nonmissing values; undefined estimates remain null.'


def table_summary(table):
    r=table['result'];kind=r.get('analysis_kind')
    if kind=='entity_comparison':
        audit=r['entity_audit'];p=audit['parameters'];name=p['measurement']['name']
        unit=' '+_md(p['measurement']['unit']) if p['measurement'].get('unit') else ''
        noun=_md(p.get('entity_label','Entities').lower());value='date' if p['comparison']['value_type']=='date' else 'value'
        target='estimated '+value if 'estimat' in p['comparison']['value_column'].lower() else 'comparison '+value
        lines=[f"- **{_md(g['classification'])}:** {number(g['mean'])}{unit}, from **{g['contributing_count']:,}** contributing {noun} out of **{g['comparable_count']:,}** comparable {noun}." for g in audit['groups']]
        exclusions=(f"**Exclusions:** {audit['missing_actual_count']:,} {noun} lack an actual {value}; "
                    f"{audit['missing_comparison_count']:,} have an actual {value} but no {target}. "
                    f"Among comparable {noun}, {audit['missing_record_count']:,} have no measurement records and "
                    f"{audit['unusable_measurement_count']:,} have records with no usable measurement.")
        return ('**'+_md(name)+' by comparison group**\n\n'+'\n'.join(lines)+'\n\n'
                f"The selected population contains **{audit['population_count']:,} {noun}**. Measurements are averaged within each entity first; each contributing entity then has equal weight. "
                +exclusions+'\n\nThis is an association, not evidence that the comparison condition caused the score difference.')
    if kind=='statistics':return statistics_summary(r,table.get('parameters',{}))
    if kind=='comparison_summary':return comparison_summary(r,detail_link=False)
    if kind=='calendar_aggregate':
        state=r['analysis_context'];metric=state['metric'];totals=r['verification']['annual_totals']
        lines=[f'- **{_md(year)}:** {value:,.2f}' for year,value in totals.items()]
        unit=f" Values are in {_md(metric['unit'])}." if metric.get('unit') else ''
        return (f"**{_md(metric['name'])} across {len(r['data'])} calendar {state['grain']}{'s' if len(r['data'])!=1 else ''}**\n\n"
                +'Annual totals:\n\n'+'\n'.join(lines)+'\n\nEmpty periods have zero sum/count.'+unit)
    if kind=='monthly_revenue':
        f=r['verification']
        if not f['matched_row_count']:
            return f"No order-detail rows matched **{f['year']}**. No monthly revenue was calculated."
        return (f"**Total revenue in {f['year']}: {f['total_revenue']:,.2f}**\n\n"
                f"The result covers **{r['row_count']} calendar months**, using {f['matched_row_count']:,} joined order-detail rows. "
                'Revenue is calculated as unit price × quantity × (1 − discount).')
    if kind=='correlation':
        corr=r['correlation'];pairs=[]
        for i,row in enumerate(corr['matrix']):
            for j,v in enumerate(row):
                if j>i and v is not None:pairs.append((abs(v),corr['columns'][i],corr['columns'][j],v))
        pairs.sort(reverse=True)
        text=f"**{corr['method'].title()} correlation across {len(corr['columns'])} measures**\n\nBased on {corr['source_observation_count']:,} source observations."
        if pairs:
            _,a,b,v=pairs[0];text+=f'\n\nStrongest absolute association: **{_md(a)}** and **{_md(b)}**, with a coefficient of **{v:.6f}**.'
        return text+'\n\n**Interpretation note:** Each coefficient uses the observations available for that pair. Undefined coefficients remain null. Correlation does not establish causation or statistical independence.'
    rows=r['data'];groups=table.get('parameters',{}).get('group_by',[])
    if len(rows)==1:
        values=[f"{_md(c)}: {number(rows[0][c])}{' '+_md(r['units'][c]) if r.get('units',{}).get(c) else ''}" for c in r['columns']]
        return values[0]+'.' if len(values)==1 else '**Calculated values**\n\n'+'\n'.join('- '+v for v in values)
    total=r.get('result_scope',{}).get('full_group_count',len(rows))
    text=f"**{len(rows):,} of {total:,} result rows calculated**"
    if groups:text+='\n\nGrouped by '+', '.join(_md(g) for g in groups)+'.'
    numeric=[c for c in r['columns'] if any(type(row[c]) in (int,float) for row in rows) and c not in groups]
    if groups and numeric:
        metric=r.get('result_scope',{}).get('sort_by') or numeric[0]
        if metric in numeric:
            ranked=sorted((row for row in rows if row[metric] is not None),key=lambda row:-row[metric])
            if ranked:
                top=ranked[0];text+=f"\n\nHighest **{_md(metric)}**: **{_md(', '.join(str(top[g]) for g in groups))}**, at **{number(top[metric])}{' '+_md(r['units'][metric]) if r.get('units',{}).get(metric) else ''}**."
    if r.get('result_scope',{}).get('limit'):text+='\n\nThis is the requested limited result.'
    return text


def render(tables, question, charts=(), *, table_in_chat=False, has_detail=None):
    summaries=[('**'+_md(t['label'])+'**\n\n' if len(tables)>1 else '')+table_summary(t) for t in tables]
    text='\n\n'.join(summaries)
    if charts and any(c.get('kind')=='result' and any(t['id']==c.get('table_id') and t['result'].get('correlation') for t in tables) for c in charts):
        text+='\n\nThe verified heatmap is available in **Open result → Chart**.'
    if has_detail is None:
        from app.services.result_presentation import disposition
        has_detail=disposition(tables,charts,table_requested=table_in_chat)['has_detail']
    if has_detail and tables and not any(t['result'].get('correlation') for t in tables) and (len(tables)>1 or any(t['parameters'].get('group_by') or len(t['result']['data'])>1 for t in tables)):
        text+='\n\nThe full breakdown is available in **Open result**.'
    if table_in_chat:
        text+='\n\n'+'\n\n'.join(markdown(t['result']) for t in tables)
    return text


def markdown(result):
    def cell(value):return number(value).replace('|','\\|').replace('\n',' ')
    columns=result['columns']
    return '\n'.join(['| '+' | '.join(columns)+' |','|'+'---|'*len(columns),
                      *['| '+' | '.join(cell(row[c]) for c in columns)+' |' for row in result['data']]])


def incomplete_summary(status,reasons,content,*,verified=False):
    heading='What is missing' if status=='incomplete' else 'Why it stopped'
    parts=[f'**Analysis {status}**','**'+heading+'**\n\n'+'\n'.join('- '+_md(reason) for reason in reasons)]
    if content:parts.append(('**Verified findings**\n\n' if verified else '')+content)
    return '\n\n'.join(parts)
