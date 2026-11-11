import json
import logging
from typing import Dict, Any
from app.llm.client import OllamaClient
from app.llm.prompts import PLANNER_USER_TEMPLATE

logger = logging.getLogger(__name__)

# The typed schema is static. Build it outside individual request budgets.
from app.analysis.operations import planner_instructions
PLANNER_CONTRACT = planner_instructions()

class QueryPlanner:
    @staticmethod
    def plan_query(user_query: str, profile: Dict[str, Any], analysis_context=None, diagnostics=None) -> Dict[str, Any]:
        """
        Classifies user query intent using schema info.
        Returns plan dictionary containing intent, reasoning, and operation parameters.
        """
        # Format schema metadata
        cols = profile.get("columns", [])
        types = profile.get("data_types", {})
        
        schema_lines = []
        for col in cols:
            dtype = types.get(col, "unknown")
            schema_lines.append(f"- Column '{col}' (Type: {dtype})")
        schema_desc = "\n".join(schema_lines)
        
        # Format sample rows preview placeholder (first 3 rows)
        sample_rows = "N/A"
        
        prompt = PLANNER_USER_TEMPLATE.format(
            schema_description=schema_desc,
            sample_rows=sample_rows,
            user_query=user_query
        )
        from app.services.output_identity import planner_history
        history_text = json.dumps(planner_history(analysis_context or {'recent_successes':[]}))
        prompt += '\nProject-local history: recent_successes are verified calculations; unresolved_request is unfulfilled intent, never a verified result. No raw result rows are included.\n' + history_text
        from app.services.metadata_service import MetadataService
        catalog=MetadataService.get_catalog_index()
        prompt += ('\nAUTHORITATIVE SOURCE CATALOG: active dataset ID is '+str(profile.get('dataset_id'))
                   +'. Source tables and join endpoints MUST use exact IDs below. database.db in the schema example is illustrative, never a real database. '
                   'Use actual column names from these tables. If the intended source is uncertain, ask for clarification.\n'
                   +json.dumps({'tables':{name:{'columns':info.get('columns',[])} for name,info in catalog.get('tables',{}).items()},
                                'relationships':catalog.get('relationships',[])}))
        
        logger.info(f"Classifying query intent: '{user_query}'")
        
        from app.analysis.operations import validate_plan, planner_instructions, sanitize, ContractError
        diagnostics=diagnostics if diagnostics is not None else []
        system=PLANNER_CONTRACT
        original=None;original_error_path=None
        for attempt in range(2):
            # Transport/auth errors are not schema failures and must never cause another call.
            decoded=None
            from app.services.request_control import report_progress
            report_progress("repairing_plan" if attempt else "planning")
            raw_response=OllamaClient.call_model(prompt=prompt,system_prompt=system,json_format=True)
            try:
                try:decoded=json.loads(raw_response)
                except (json.JSONDecodeError,TypeError) as error:raise ContractError('$','invalid JSON: '+str(error)) from None
                plan=validate_plan(decoded,history=analysis_context or {})
                if attempt and original is not None:
                    from app.analysis.operations import guard_repair
                    guard_repair(original,decoded,original_error_path,history=analysis_context or {})
                if plan.get('analysis_plan') and plan.get('context_action')=='inherit':
                    from app.services.specification_context import validate_followup
                    validate_followup(plan['analysis_plan'],analysis_context or {},plan.get('reference_message_id'),plan.get('changed_fields',[]))
            except (ValueError,TypeError) as error:
                from app.services.output_identity import OutputIdentityError
                diagnostic={'attempt':attempt+1,'accepted':False,'error':sanitize(str(error)),
                            'output':sanitize(decoded if decoded is not None else raw_response)}
                diagnostics.append(diagnostic)
                logger.info('Planner diagnostic: %s',json.dumps(diagnostic))
                if isinstance(error,OutputIdentityError):raise
                if not attempt:original=decoded;original_error_path=getattr(error,"path",None)
                if attempt:raise ValueError('Planner schema repair exhausted after one attempt. '+str(error)) from None
                prompt += ('\nSCHEMA REPAIR (only one attempt): '+str(error)+
                           '\nRejected output: '+json.dumps(sanitize(decoded if decoded is not None else raw_response))+
                           '\nReturn the same requested calculation in the valid typed schema. Preserve population, distinctness, formula, years, sources, units and scope. Do not simplify or substitute a different calculation.')
                continue
            diagnostic={'attempt':attempt+1,'accepted':True,'output':sanitize(plan)}
            diagnostics.append(diagnostic);logger.info('Planner diagnostic: %s',json.dumps(diagnostic))
            return plan

class CodeGenerator:
    @staticmethod
    def generate_code(user_query: str, profile: Dict[str, Any]) -> str:
        """
        Generates Python code for complex analysis queries.
        """
        # Format schema metadata
        cols = profile.get("columns", [])
        types = profile.get("data_types", {})
        
        schema_lines = []
        for col in cols:
            dtype = types.get(col, "unknown")
            schema_lines.append(f"- '{col}' ({dtype})")
        schema_desc = "\n".join(schema_lines)
        
        system_prompt = (
            "You are an expert Python data analyst. Generate safe, self-contained Python code "
            "to answer the user's question. A pandas DataFrame named `df` is already pre-loaded "
            "in the global scope.\n\n"
            "Rules:\n"
            "1. Operate ONLY on the pre-loaded global variable `df`.\n"
            "2. Print findings or outputs using standard print() calls.\n"
            "3. MATHEMATICAL ACCURACY: Always use explicit parentheses `(...)` around numerators (e.g. `(df['goals'] + df['assists']) / df['minutes_played']`). Never write `a + b / c` without parentheses!\n"
            "4. If visualization is requested, write a plotly interactive plot or matplotlib figure "
            "to the file path `output_chart.html` or `output_chart.png`.\n"
            "5. Return ONLY executable Python code. Do not wrap in markdown or add explanations. "
            "Do not import forbidden libraries (os, sys, subprocess, requests, socket)."
        )
        
        prompt = (
            f"Dataset columns:\n{schema_desc}\n\n"
            f"User request: {user_query}\n\n"
            "Generate the Python script now:"
        )
        
        logger.info(f"Generating Python code snippet for: '{user_query}'")
        raw_code = OllamaClient.call_model(prompt=prompt, system_prompt=system_prompt)
        
        # Clean markdown wrappers if present
        clean_code = raw_code.strip()
        if clean_code.startswith("```python"):
            clean_code = clean_code.split("```python", 1)[1]
        elif clean_code.startswith("```"):
            clean_code = clean_code.split("```", 1)[1]
            
        if clean_code.endswith("```"):
            clean_code = clean_code.rsplit("```", 1)[0]
            
        return clean_code.strip()
