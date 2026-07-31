import json
import logging
from typing import Dict, Any
from app.llm.client import OllamaClient
from app.llm.prompts import PLANNER_SYSTEM_PROMPT, PLANNER_USER_TEMPLATE

logger = logging.getLogger(__name__)

class QueryPlanner:
    @staticmethod
    def plan_query(user_query: str, profile: Dict[str, Any]) -> Dict[str, Any]:
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
        
        logger.info(f"Classifying query intent: '{user_query}'")
        
        try:
            # Request JSON response from Ollama
            raw_response = OllamaClient.call_model(
                prompt=prompt,
                system_prompt=PLANNER_SYSTEM_PROMPT,
                json_format=True
            )
            logger.debug(f"Planner raw output: {raw_response}")
            
            # Parse response
            plan = json.loads(raw_response)
            return plan
        except Exception as e:
            logger.error(f"Failed to parse planner output or make connection: {e}")
            # Fallback to CONVERSATION mode
            return {
                "intent": "CONVERSATION",
                "reasoning": f"Fallback triggered due to planner parsing failure: {e}",
                "operation": {"type": None, "parameters": {}}
            }
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
