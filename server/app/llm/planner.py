import json
import logging
from typing import Dict, Any
from app.llm.client import OllamaClient
from app.llm.prompts import PLANNER_SYSTEM_PROMPT, PLANNER_USER_TEMPLATE

logger = logging.getLogger(__name__)

class QueryPlanner:
    @staticmethod
    def plan_query(user_query: str, profile: Dict[str, Any], analysis_context=None) -> Dict[str, Any]:
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
        from app.services.analysis_context import CONTEXT_INSTRUCTIONS
        prompt += '\n' + CONTEXT_INSTRUCTIONS + '\nSuccessful analysis history (no raw rows):\n' + json.dumps(analysis_context or {'recent_successes':[]})
        from app.services.metadata_service import MetadataService
        catalog=MetadataService.get_catalog_index()
        prompt += ('\nAUTHORITATIVE SOURCE CATALOG: active dataset ID is '+str(profile.get('dataset_id'))
                   +'. Source tables and join endpoints MUST use exact IDs below. database.db in the schema example is illustrative, never a real database. '
                   'Use actual column names from these tables. If the intended source is uncertain, ask for clarification.\n'
                   +json.dumps({'tables':{name:{'columns':info.get('columns',[])} for name,info in catalog.get('tables',{}).items()},
                                'relationships':catalog.get('relationships',[])}))
        
        logger.info(f"Classifying query intent: '{user_query}'")
        
        # Provider errors propagate: they must never become a conversation request.
        raw_response = OllamaClient.call_model(
            prompt=prompt, system_prompt=PLANNER_SYSTEM_PROMPT, json_format=True
        )
        try:
            plan = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError):
            raise ValueError("The model returned an invalid query plan. The analysis stopped.") from None
        if not isinstance(plan, dict) or plan.get("intent") not in {"SIMPLE", "COMPLEX", "CONVERSATION"}:
            raise ValueError("The model returned an unsupported query intent. The analysis stopped.")
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
