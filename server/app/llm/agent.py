"""
Agent: The multi-turn loop that thinks, acts, and observes.

Flow:
  1. Receives the classified intent + user query
  2. Picks the right tool prompt (SIMPLE / COMPLEX / CONVERSATION)
  3. Loops: ask LLM → parse action → execute tool → feed result back
  4. Stops when LLM says "final_answer" or max turns reached
"""

import json
import ast
import hashlib
import re
import logging
from typing import Dict, Any, Optional
from app.services.dataset_manager import DatasetManager
from app.services.metadata_service import MetadataService
from app.llm.client import OllamaClient
from app.llm.prompts import (
    SIMPLE_TOOLS_PROMPT,
    COMPLEX_TOOLS_PROMPT,
    CONVERSATION_TOOLS_PROMPT,
    AGENT_SYSTEM_TEMPLATE,
)

logger = logging.getLogger(__name__)

# Which tools are allowed for each intent
ALLOWED_TOOLS = {
    "SIMPLE": {"comparison_summary", "monthly_revenue", "aggregation", "filtering", "statistics", "correlation", "visualization"},
    "COMPLEX": {"run_code"},
    "CONVERSATION": set(),  # no tools
}

# Map intent → tool prompt
TOOL_PROMPTS = {
    "SIMPLE": SIMPLE_TOOLS_PROMPT,
    "COMPLEX": COMPLEX_TOOLS_PROMPT,
    "CONVERSATION": CONVERSATION_TOOLS_PROMPT,
}


class Agent:
    """
    A simple multi-turn agent that:
    - Gets a system prompt with allowed tools for the intent
    - Calls the LLM in a loop
    - Executes tool calls and feeds observations back
    - Returns when the LLM produces a final_answer
    """

    @staticmethod
    def run(
        user_query: str,
        intent: str,
        profile: Dict[str, Any],
        dataset_id: str,
        project_id: Optional[str] = None,
        db: Any = None,
        max_turns: int = 5,
        emit=None,
        analysis_context=None,
        resolved_analysis=None,
        resolved_tool=None,
        completion_contract=None,
    ) -> Dict[str, Any]:
        """
        Main entry point. Returns a dict with:
          - content: the final text answer
          - type: "text" | "table" | "code"
          - results: (optional) raw data from tool execution
          - code: (optional) generated code for COMPLEX
          - artifacts: typed, persisted chart references
        """

        # --- 0. Table Selection Step (Pre-query routing) ---
        from app.llm.table_selector import TableSelector
        emit = emit or (lambda stage: None)
        if intent in {"SIMPLE", "COMPLEX"}:
            emit("selecting_tables")
        if intent in {'SIMPLE','COMPLEX'}:
            selection = TableSelector.select_tables(user_query,dataset_id,analysis_context=analysis_context,
                resolved_source=resolved_analysis.get('source') if resolved_analysis else None) if analysis_context or resolved_analysis else TableSelector.select_tables(user_query,dataset_id)
        else:
            selection = {}
        selected_tables = list(dict.fromkeys(selection.get("tables_needed", [dataset_id])))
        join_keys = selection.get("join_keys", []) if len(selected_tables) > 1 else []
        source = {"tables": selected_tables, "join_keys": join_keys}
        from app.services.analysis_package import OutputAccumulator
        outputs=OutputAccumulator()
        separate_sources=bool(completion_contract and len(completion_contract['outputs'])>1 and all(s.get('source_tables') for s in completion_contract['outputs']))
        logger.info('Resolved analysis source: %s',source)
        steps = []
        failed_calls = {}
        dataframe = None
        try:
            if not separate_sources and (len(selected_tables) > 1 or (
                intent == "COMPLEX" and "::" in selected_tables[0]
            )):
                dataframe = DatasetManager.load_joined_dataframe(selected_tables, join_keys)
        except Exception as error:
            return {
                "failed": True,
                "content": "I could not prepare the tables for analysis.",
                "type": "text",
                "calculation": {"steps": [{"tool": "Prepare tables", "status": "failed", "error": str(error), **source}]},
            }
        dataset_id = selected_tables[0]
        initial_tool_failure=None
        comparison_required=bool(resolved_tool and resolved_tool.get('tool')=='comparison_summary')
        if resolved_tool:
            emit('running_tool')
            observation,result=_execute_tool(resolved_tool['tool'],resolved_tool['parameters'],dataset_id,db,profile,
                                             project_id=project_id,dataframe=dataframe)
            step={'tool':resolved_tool['tool'],'parameters':resolved_tool['parameters'],'status':'succeeded' if result else 'failed',**source}
            if not result:
                step['error']=observation
                steps.append(step)
                failed_calls[_tool_fingerprint(resolved_tool['tool'],resolved_tool['parameters'])]=observation
                initial_tool_failure=(resolved_tool,observation)
            else:
                from app.analysis.comparison_summary import explanation as compare_explanation
                return {'type':'table','content':compare_explanation(result),'results':result,'calculation':{'steps':[step]}}
        if resolved_analysis:
            from app.analysis.calendar import calculate, explanation as calendar_explanation
            resolved_analysis={**resolved_analysis,'source':{**source,'database':dataset_id.split('::',1)[0]}}
            emit('running_tool')
            step={'tool':'calendar_aggregate','parameters':resolved_analysis,'status':'failed',**source}
            try:
                if dataframe is None:
                    dataframe=DatasetManager.load_dataset_dataframe(DatasetManager.get_dataset(db,dataset_id))
                results=calculate(dataframe,resolved_analysis)
            except (ValueError,TypeError,KeyError) as error:
                step['error']=str(error)
                return {'failed':True,'type':'text','content':f'I could not calculate the calendar analysis: {error}','calculation':{'steps':[step]}}
            step['status']='succeeded'
            emit('preparing_answer')
            return {'type':'table','content':calendar_explanation(results),'results':results,
                    'analysis_context':results['analysis_context'],'calculation':{'steps':[step]}}

        # Standard calendar-month revenue is a supported deterministic calculation.
        # The model selects source tables; it cannot replace the calculation with a preview.
        from app.analysis.monthly_revenue import requested_year, explanation
        monthly_year = requested_year(user_query)
        if monthly_year is not None:
            parameters = {"year":monthly_year,"date_column":"OrderDate","unit_price_column":"UnitPrice",
                          "quantity_column":"Quantity","discount_column":"Discount"}
            emit("running_tool")
            observation, results = _execute_tool('monthly_revenue',parameters,dataset_id,db,profile,
                                                 project_id=project_id,dataframe=dataframe)
            step = {"tool":"monthly_revenue","parameters":parameters,"status":"succeeded" if results is not None else "failed",**source}
            if results is None:
                step['error'] = observation
                return {"failed":True,"type":"text","content":"I could not calculate monthly revenue. "+observation,
                        "calculation":{"steps":[step]}}
            emit("preparing_answer")
            return {"content":explanation(results),"type":"table","results":results,"calculation":{"steps":[step]}}

        from app.analysis.chart_consistency import wants_order_total_histogram, order_total_expectation, order_total_explanation
        chart_expectation = None
        if intent == 'COMPLEX' and wants_order_total_histogram(user_query):
            try:
                if dataframe is None:
                    dataset = DatasetManager.get_dataset(db,dataset_id)
                    dataframe = DatasetManager.load_dataset_dataframe(dataset)
                chart_expectation = order_total_expectation(dataframe)
            except (ValueError, TypeError) as error:
                return {'failed': True, 'type': 'text',
                        'content': f'I could not prepare the requested order-total population: {error}'}

        # Fetch targeted profiles ONLY for selected tables
        targeted_profiles = []
        for t_id in selected_tables:
            p = MetadataService.get_profile(t_id)
            if p:
                targeted_profiles.append(p)

        if not targeted_profiles:
            targeted_profiles = [profile]

        from app.analysis.correlation import is_correlation_request, requested_columns
        requires_correlation = intent in {'SIMPLE', 'COMPLEX'} and is_correlation_request(user_query)
        correlation_request = None
        if requires_correlation and intent == 'COMPLEX':
            if dataframe is None:
                dataframe = DatasetManager.load_dataset_dataframe(DatasetManager.get_dataset(db, dataset_id))
            named = requested_columns(user_query, dataframe.columns)
            correlation_request = {'method': 'spearman' if re.search(r'\bspearman\b', user_query, re.I) else 'pearson'}
            if named:
                correlation_request['columns'] = named

        # Combine schema descriptions for selected tables
        if dataframe is not None:
            # Describe the actual Python input, not separate pre-join schemas.
            schema_desc = (
                "PYTHON INPUT CONTRACT: `df` is already prepared by the backend.\n"
                + ("The requested tables have ALREADY BEEN JOINED. Do not join them again or merge df with a slice of itself.\n" if len(selected_tables) > 1 else "The selected table is already loaded.\n")
                + "Source tables: " + json.dumps(selected_tables)
                + "\nApplied join keys: " + json.dumps(join_keys)
                + f"\nInput rows: {len(dataframe)}. Preserve individual observations for distribution/box plots."
                + "\nUse these exact dataframe column names and types: "
                + json.dumps({column: str(dtype) for column, dtype in dataframe.dtypes.items()})
            )
            if {'CategoryName', 'UnitPrice'}.issubset(dataframe.columns):
                schema_desc += "\nFor a product-price box plot, use px.box(df, x='CategoryName', y='UnitPrice') directly; each row is already a joined observation."
        else:
            schema_desc = "\n\n".join([_format_schema(p) for p in targeted_profiles])
        if chart_expectation:
            schema_desc += (
                "\nREQUESTED OBSERVATION CONTRACT: each histogram observation must be one ORDER, not one line item. "
                + f"Input has {chart_expectation['input_line_count']} line items belonging to {chart_expectation['count']} orders. "
                + "First compute UnitPrice * Quantity * (1 - Discount), then SUM by OrderID. Plot the resulting order totals. "
                + "Histograms are checked against the actual per-order values; changing a title cannot satisfy this contract."
            )
        tool_prompt = TOOL_PROMPTS.get(intent, CONVERSATION_TOOLS_PROMPT)
        if analysis_context:
            schema_desc += '\nRelevant successful analysis context (retain only explicitly referenced facts): '+json.dumps(analysis_context)
        if correlation_request is not None:
            schema_desc += ('\nCORRELATION RESULT CONTRACT: compute df[requested_columns].corr(method="'
                            + correlation_request['method'] + '"). The sandbox captures and validates this numeric matrix. '
                            'Open result displays that same matrix as Table and a heatmap fixed at -1 to +1, centered at zero. '
                            'A PNG or printed matrix alone cannot replace the structured result. Requested columns: '
                            + json.dumps(correlation_request.get('columns', 'all non-ID numeric measures')))

        if completion_contract:
            schema_desc += '\nREQUESTED OUTPUT CONTRACT (satisfy every output; use its output_id):\n'+json.dumps(completion_contract)

        system_prompt = AGENT_SYSTEM_TEMPLATE.format(
            schema_description=schema_desc,
            tool_prompt=tool_prompt,
            max_turns=max_turns,
        )

        # --- 2. Initialize message history ---
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query},
        ]
        if initial_tool_failure:
            failed_tool,error=initial_tool_failure
            from app.analysis.comparison_summary import contract_instructions
            messages.extend([{'role':'assistant','content':json.dumps({'action':'tool_call',**failed_tool})},
                             {'role':'user','content':'The planner-selected calculation failed: '+error+'\nCorrect the arguments using this contract, preserving the requested eligibility population. Do not repeat the same failed call or finalize an unrelated result.\n'+contract_instructions()}])

        # Track results across turns
        last_results = None
        last_code = None
        last_artifacts = []
        response_type = "text"

        def finish_answer(content):
            comparison_rate=comparison_required or bool(re.search(r'percent|percentage|proportion|\brate\b',user_query,re.I) and
                                 re.search(r'after|before|late|earlier|exceed|greater|less than',user_query,re.I) and
                                 re.search(r'date|deliver|arriv',user_query,re.I))
            if comparison_rate and (not last_results or last_results.get('analysis_kind')!='comparison_summary'):
                return {'failed':True,'type':'text','content':'The requested comparison percentage was not calculated. A partial filter or unrelated count cannot complete this request. Use comparison_summary with explicit column references.', 'calculation':{'steps':steps},'analysis_outputs':outputs.export()}
            if requires_correlation and (not last_results or last_results.get('analysis_kind') != 'correlation'):
                return {'failed':True,'type':'text','content':'No validated numeric correlation matrix was returned. A chart image alone cannot answer this request.',
                    'calculation':{'steps':steps},'analysis_outputs':outputs.export()}
            requires_monthly = intent == 'SIMPLE' and re.search(r'\bmonthly\s+revenue\b', user_query, re.I) and re.search(r'\b\d{4}\b', user_query)
            verified_monthly = last_results is not None and last_results.get('analysis_kind') == 'monthly_revenue'
            if requires_monthly and not verified_monthly:
                error = 'Monthly revenue was requested, but no verified monthly aggregate was calculated. Raw rows or previews cannot answer this request.'
                return {'failed':True,'content':error,'type':'text','calculation':{'steps':steps},'analysis_outputs':outputs.export()}
            if verified_monthly:
                content = explanation(last_results)
            if last_results and last_results.get('analysis_kind') in {'aggregation','comparison_summary'}:
                from app.analysis.result_operations import explanation as aggregate_explanation
                from app.analysis.comparison_summary import explanation as comparison_explanation
                content=aggregate_explanation(last_results) if last_results['analysis_kind']=='aggregation' else comparison_explanation(last_results)
            if last_results and last_results.get('analysis_kind') == 'correlation':
                from app.analysis.correlation import explanation as correlation_explanation
                content = correlation_explanation(last_results)
            if chart_expectation:
                if not last_artifacts or not all(artifact.get('population',{}).get('verified') and artifact.get('population',{}).get('fingerprint') == chart_expectation['fingerprint'] for artifact in last_artifacts):
                    return {'failed':True,'content':'No chart of the requested per-order population was verified. Line-item charts are not an answer to this request.','type':'text','calculation':{'steps':steps}}
                content = order_total_explanation(chart_expectation)
                return {'content':content,'type':'code','results':None,
                        'calculation':{'steps':steps},'code':last_code,'artifacts':last_artifacts}
            return {'content':content,'type':response_type,'results':last_results,'analysis_outputs':outputs.export(),
                    'calculation':{'steps':steps} if steps else None,'code':last_code,'artifacts':last_artifacts}

        # --- 3. Agent loop ---
        if intent == "CONVERSATION":
            emit("preparing_answer")
        for turn in range(max_turns):
            logger.info(f"Agent turn {turn + 1}/{max_turns} | intent={intent}")

            # Call LLM with full message history
            try:
                raw_response = OllamaClient.call_model_chat(messages, json_format=True)
            except Exception:
                if outputs.tables:
                    if steps and steps[-1]['status']=='succeeded':return finish_answer('')
                    return {'failed':True,'type':'text','content':'Execution stopped after an unsuccessful step.','calculation':{'steps':steps},'analysis_outputs':outputs.export()}
                if (last_artifacts or (last_results and last_results.get('analysis_kind') == 'correlation')) and steps and steps[-1]["status"] == "succeeded":
                    return finish_answer("The chart was generated successfully. The model could not prepare the final explanation; open the captured result below.")
                raise
            logger.debug(f"Agent raw response: {raw_response}")

            # Parse the LLM's JSON response
            try:
                action = json.loads(raw_response)
            except json.JSONDecodeError:
                if steps and steps[-1]["status"] == "failed":
                    break
                return finish_answer(raw_response)

            # --- 4. Handle the action ---

            # Case A: Agent is done, return final answer
            if action.get("action") == "final_answer":
                if steps and steps[-1]["status"] == "failed":
                    break
                return finish_answer(action.get("content", ""))

            # Case B: Agent wants to call a tool
            if action.get("action") == "tool_call":
                tool_name = action.get("tool", "")
                parameters = action.get("parameters", {})
                parameters=dict(parameters)
                output_id=parameters.pop('output_id',None)
                if tool_name=='comparison_summary':comparison_required=True

                # Validate: is this tool allowed for this intent?
                allowed = ALLOWED_TOOLS.get(intent, set())
                if tool_name not in allowed:
                    observation = f"ERROR: Tool '{tool_name}' is not available. Allowed tools: {list(allowed)}"
                    messages.append({"role": "assistant", "content": raw_response})
                    messages.append({"role": "user", "content": observation})
                    continue

                if tool_name == 'correlation' and isinstance(parameters, dict):
                    from app.analysis.correlation import requested_columns
                    available = list(dataframe.columns) if dataframe is not None else [column for p in targeted_profiles for column in p.get('columns', [])]
                    named = requested_columns(user_query, available)
                    if named:
                        parameters['columns'] = named
                if tool_name=='aggregation' and isinstance(parameters,dict):
                    from app.analysis.result_operations import normalize_request
                    parameters=normalize_request(parameters,user_query)
                    from app.services.analysis_package import apply_output_contract
                    parameters=apply_output_contract(parameters,completion_contract,output_id)
                fingerprint = _tool_fingerprint(tool_name, parameters)
                if output_id is not None:fingerprint=(*fingerprint,output_id)
                if fingerprint in failed_calls:
                    error = ("The model repeated a previously failed tool call without correcting it. "
                             "The duplicate was not executed. Original error: " + failed_calls[fingerprint])
                    steps.append({"tool": tool_name, "parameters": parameters, "status": "failed",
                                  "execution_skipped": True, "error": error, **source})
                    return {"failed": True, "type": "text", "content": "I could not complete the calculation. " + error,
                            "calculation": {"steps": steps},'analysis_outputs':outputs.export()}

                # Execute the tool and get the observation
                emit("running_tool")
                if tool_name=='visualization':
                    try:
                        outputs.record(tool_name,parameters,{},source,len(steps),output_id,completion_contract)
                        observation='Chart specification attached to the calculated result. The result data is unchanged.'
                        tool_results={'presentation_only':True}
                    except ValueError as error:
                        observation=str(error);tool_results=None
                else:
                    tool_source=source;tool_frame=dataframe;tool_dataset=dataset_id
                    try:
                        if separate_sources:
                            spec=next((s for s in completion_contract['outputs'] if s['id']==output_id),None)
                            if spec is None:raise ValueError('Multiple source outputs require an explicit output_id.')
                            names=spec['source_tables']
                            if not set(names)<=set(selected_tables):raise ValueError('Output sources must be exact table IDs from the validated selection.')
                            keys=[k for k in join_keys if k['from_table'] in names and k['to_table'] in names]
                            tool_frame=DatasetManager.load_joined_dataframe(names,keys)
                            tool_dataset=names[0];tool_source={'tables':names,'join_keys':keys}
                        observation, tool_results = _execute_tool(
                            tool_name, parameters, tool_dataset, db, profile, project_id=project_id, dataframe=tool_frame, chart_expectation=chart_expectation,
                            correlation_request=correlation_request
                        )
                        if tool_results is not None:outputs.record(tool_name,parameters,tool_results,tool_source,len(steps),output_id,completion_contract)
                    except (ValueError,TypeError,KeyError) as error:observation=str(error);tool_results=None

                step = {
                    "tool": tool_name,
                    "parameters": parameters,
                    "status": "succeeded" if tool_results is not None else "failed",
                    **(tool_source if tool_name!='visualization' else source),
                }
                if tool_results is None:
                    step["error"] = observation
                    failed_calls[fingerprint] = observation
                steps.append(step)

                # Track results for the response
                if tool_results:
                    if turn + 1 < max_turns:
                        emit("preparing_answer")
                    if tool_name == "run_code":
                        last_code = parameters.get("code", "")
                        if correlation_request is not None:
                            last_results = tool_results.get('results')
                        elif tool_results.get('verified_tables'):
                            last_results=tool_results['verified_tables'][0]['result']
                        generated = tool_results.get('artifacts', [])
                        if generated:
                            for artifact in generated:
                                artifact['provenance'] = {'step_index':len(steps)-1,'tool':'run_code',
                                    'code_fingerprint':hashlib.sha256(_tool_fingerprint('run_code',parameters)[1].encode()).hexdigest(),**tool_source}
                            step['artifact_ids'] = [artifact['id'] for artifact in generated]
                            # Preserve independently addressable exports; publication validates calculation outputs.
                            last_artifacts.extend(generated)
                        response_type = "table" if last_results and last_results.get('analysis_kind') == 'correlation' else "code"
                    elif tool_name!='visualization':
                        last_results = tool_results
                        response_type = "table" if tool_results.get("columns") and isinstance(tool_results.get("data"), list) else "text"

                # Add this exchange to message history so agent sees what happened
                messages.append({"role": "assistant", "content": raw_response})
                messages.append({"role": "user", "content": f"OBSERVATION:\n{observation}" + ("\nThe tool failed. Correct the cause before retrying; identical failed calls will not run again. The input df is unchanged between calls; use its exact supplied schema." if tool_results is None else "")})
                continue

            # Case C: Unknown action — ask agent to try again
            messages.append({"role": "assistant", "content": raw_response})
            messages.append({"role": "user", "content": "ERROR: Invalid action. Use 'tool_call' or 'final_answer'."})

        if steps and steps[-1]["status"] == "failed":
            return {
                "failed": True,
                "content": f"I could not complete the calculation. {steps[-1]['error']}",
                "type": "text",
                "calculation": {"steps": steps},
                'analysis_outputs':outputs.export(),
            }

        # Max turns exhausted — return whatever we have
        if requires_correlation:
            return finish_answer('')
        return {
            "calculation": {"steps": steps} if steps else None,
            "failed": True,
            "content": "I was unable to fully complete the analysis within the allowed steps.",
            "type": response_type,
            "results": None,
            "code": last_code,
            "artifacts": last_artifacts,
            "analysis_outputs": outputs.export(),
        }


# ============================================================
# Helper: format schema for the prompt
# ============================================================

def _tool_fingerprint(tool_name, parameters):
    """Ignore formatting/comments when recognizing an unchanged failed program."""
    normalized = dict(parameters)
    if tool_name=='comparison_summary':
        from app.analysis.comparison_summary import normalize_parameters
        try:normalized=normalize_parameters(parameters)
        except ValueError:pass
    if tool_name == 'run_code' and isinstance(parameters.get('code'), str):
        try:
            normalized['code'] = ast.dump(ast.parse(parameters['code']), include_attributes=False)
        except SyntaxError:
            normalized['code'] = parameters['code'].strip()
    return tool_name, json.dumps(normalized, sort_keys=True, default=str)


def _format_schema(profile: Dict[str, Any]) -> str:
    """Turn dataset profile into a readable schema string."""
    cols = profile.get("columns", [])
    types = profile.get("data_types", {})

    lines = []
    for col in cols:
        dtype = types.get(col, "unknown")
        lines.append(f"- {col} ({dtype})")
    return "\n".join(lines)


# ============================================================
# Helper: execute a tool call and return (observation_text, raw_results)
# ============================================================

def _execute_tool(
    tool_name: str,
    parameters: Dict[str, Any],
    dataset_id: str,
    db,
    profile: Dict[str, Any],
    project_id: Optional[str] = None,
    *, dataframe=None, chart_expectation=None, correlation_request=None,
) -> tuple:
    """
    Runs the requested tool and returns:
      (observation_string, raw_results_dict)

    The observation is what gets fed back to the agent.
    The raw_results is what gets returned to the frontend.
    """

    # --- SIMPLE tools: use AnalysisEngine ---
    if tool_name in {"comparison_summary", "monthly_revenue", "aggregation", "filtering", "statistics", "correlation", "visualization"}:
        try:
            from app.analysis_engine import AnalysisEngine

            # Build the execution plan in the format AnalysisEngine expects
            exec_plan = {}
            if tool_name == "aggregation":
                exec_plan["aggregation"] = parameters
            elif tool_name=='comparison_summary':
                from app.analysis.comparison_summary import normalize_parameters
                exec_plan['comparison_summary']=normalize_parameters(parameters)
            elif tool_name == "monthly_revenue":
                exec_plan["monthly_revenue"] = parameters
            elif tool_name == "filtering":
                if not isinstance(parameters,dict) or set(parameters) != {'filters'}:
                    raise ValueError('Filtering expects {"filters":[{"column":"OrderDate","operator":">=","value":"2022-01-01"},{"column":"OrderDate","operator":"<","value":"2023-01-01"}]}. Unknown fields cannot be ignored.')
                exec_plan["filters"] = parameters['filters']
            elif tool_name == "statistics":
                exec_plan["statistics"] = parameters
            elif tool_name == "correlation":
                if not isinstance(parameters, dict) or set(parameters) - {'method', 'columns'}:
                    raise ValueError('Correlation expects {"method":"pearson","columns":["UnitPrice","Quantity","Discount"]}.')
                exec_plan["correlation"] = True
                exec_plan["correlation_method"] = parameters.get("method", "pearson")
                exec_plan['correlation_columns'] = parameters.get('columns')
            elif tool_name == "visualization":
                exec_plan["visualization"] = parameters

            results = AnalysisEngine.execute_plan(db, dataset_id, exec_plan, dataframe=dataframe, validate_tool_arguments=True)

            # Build a concise observation for the agent
            observation = _summarize_results(results)
            return observation, results

        except Exception as e:
            error_msg = f"Tool '{tool_name}' failed: {e}"
            logger.error(error_msg)
            return error_msg, None

    # --- COMPLEX tool: use SandboxRunner ---
    if tool_name == "run_code":
        try:
            from app.sandbox.runner import SandboxRunner
            from app.services.dataset_manager import DatasetManager

            code = parameters.get("code", "")
            db_dataset = DatasetManager.get_dataset(db, dataset_id)
            if not db_dataset:
                return "ERROR: Dataset not found.", None

            run_result = SandboxRunner.run_code(dataset_id=dataset_id, python_code=code, project_id=project_id, dataframe=dataframe, chart_expectation=chart_expectation, correlation_request=correlation_request)

            SandboxRunner.cleanup(run_result)

            if run_result.get("success"):
                stdout = run_result.get("stdout", "")
                variables = run_result.get("variables", {})
                observation = f"Code executed successfully.\nOutput:\n{stdout}"
                if run_result.get("artifacts"):
                    observation += f"\nCaptured final-chart candidates: {json.dumps([{'id':a['id'],'title':a.get('title'),'population':a.get('population')} for a in run_result['artifacts']])}. Exports alone do not establish completion. Export named analysis_tables and analysis_plans for verified calculation outputs."
                if variables:
                    observation += f"\nVariables: {json.dumps(variables, indent=2)}"
                return observation, {
                    "stdout": stdout,
                    "variables": variables,
                    "artifacts": run_result.get("artifacts", []),
                    "results": run_result.get('results'),
                    "verified_tables":run_result.get('verified_tables',[]),
                }
            else:
                error = run_result.get("error", "Unknown error")
                return f"Code execution failed with error:\n{error}", None

        except Exception as e:
            error_msg = f"Sandbox execution failed: {e}"
            logger.error(error_msg)
            return error_msg, None

    return f"Unknown tool: {tool_name}", None


def _summarize_results(results: Dict[str, Any]) -> str:
    """Turn raw AnalysisEngine results into a compact text observation for the agent."""
    if results.get('analysis_kind') == 'correlation':
        from app.analysis.correlation import explanation as correlation_explanation
        return correlation_explanation(results) + '\nNow return final_answer; the matrix is already available for Open result. No visualization tool is needed.'
    parts = []

    # If statistical summary is present, format clean readable summary
    if results.get("statistics"):
        parts.append("Calculated Statistics:")
        for col, s in results["statistics"].items():
            out_vals = s.get("outlier_values", [])
            parts.append(
                f"- {col}: mean={s.get('mean')}, std={s.get('std')}, min={s.get('min')}, "
                f"median={s.get('median')}, max={s.get('max')}, "
                f"outliers_count={s.get('outliers_count')}, outlier_values={out_vals}"
            )
        parts.append("\nNow respond with your final_answer in valid JSON format.")
        return "\n".join(parts)

    data = results.get("data", [])
    columns = results.get("columns", [])
    row_count = results.get("row_count", 0)

    parts.append(f"Returned {row_count} rows with columns: {columns}")

    audit = results.get('filter_audit')
    if audit:
        parts.append('Validated filter audit: ' + json.dumps(audit))
        parts.append('An unchanged result means every row matched these predicates; it is NOT evidence that a year is absent.')

    # Show first 5 rows as preview
    preview = data[:5]
    if preview:
        parts.append("Preview rows are NOT exhaustive and cannot establish the date range or absence of a year.")
        parts.append(f"Preview (first {len(preview)} rows):")
        for row in preview:
            parts.append(f"  {row}")

    if results.get("correlation"):
        parts.append(f"Correlation: {json.dumps(results['correlation'], indent=2)}")

    if results.get("visualization_blueprint"):
        parts.append(f"Chart blueprint: {json.dumps(results['visualization_blueprint'])}")

    parts.append("\nNow respond with your final_answer in valid JSON format.")
    return "\n".join(parts)
