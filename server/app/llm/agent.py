"""
Agent: The multi-turn loop that thinks, acts, and observes.

Flow:
  1. Receives the classified intent + user query
  2. Picks the right tool prompt (SIMPLE / COMPLEX / CONVERSATION)
  3. Loops: ask LLM → parse action → execute tool → feed result back
  4. Stops when LLM says "final_answer" or max turns reached
"""

import json
import logging
from typing import Dict, Any

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
    "SIMPLE": {"aggregation", "filtering", "statistics", "correlation", "visualization"},
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
    ) -> Dict[str, Any]:
        """
        Main entry point. Returns a dict with:
          - content: the final text answer
          - type: "text" | "table" | "code"
          - results: (optional) raw data from tool execution
          - code: (optional) generated code for COMPLEX
          - chart_base64: (optional) chart image
        """

        # --- 1. Build the system prompt with schema + tool instructions ---
        schema_desc = _format_schema(profile)
        tool_prompt = TOOL_PROMPTS.get(intent, CONVERSATION_TOOLS_PROMPT)

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

        # Track results across turns
        last_results = None
        last_code = None
        last_chart_base64 = None
        response_type = "text"

        # --- 3. Agent loop ---
        for turn in range(max_turns):
            logger.info(f"Agent turn {turn + 1}/{max_turns} | intent={intent}")

            # Call LLM with full message history
            raw_response = OllamaClient.call_model_chat(messages, json_format=True)
            logger.debug(f"Agent raw response: {raw_response}")

            # Parse the LLM's JSON response
            try:
                action = json.loads(raw_response)
            except json.JSONDecodeError:
                # LLM didn't return valid JSON — treat as final answer text
                return {
                    "content": raw_response,
                    "type": "text",
                }

            # --- 4. Handle the action ---

            # Case A: Agent is done, return final answer
            if action.get("action") == "final_answer":
                return {
                    "content": action.get("content", ""),
                    "type": response_type,
                    "results": last_results,
                    "code": last_code,
                    "chart_base64": last_chart_base64,
                }

            # Case B: Agent wants to call a tool
            if action.get("action") == "tool_call":
                tool_name = action.get("tool", "")
                parameters = action.get("parameters", {})

                # Validate: is this tool allowed for this intent?
                allowed = ALLOWED_TOOLS.get(intent, set())
                if tool_name not in allowed:
                    observation = f"ERROR: Tool '{tool_name}' is not available. Allowed tools: {list(allowed)}"
                    messages.append({"role": "assistant", "content": raw_response})
                    messages.append({"role": "user", "content": observation})
                    continue

                # Execute the tool and get the observation
                observation, tool_results = _execute_tool(
                    tool_name, parameters, dataset_id, db, profile, project_id=project_id
                )

                # Track results for the response
                if tool_results:
                    if tool_name == "run_code":
                        last_code = parameters.get("code", "")
                        last_chart_base64 = tool_results.get("chart_base64")
                        response_type = "code"
                    else:
                        last_results = tool_results
                        response_type = "table"

                # Add this exchange to message history so agent sees what happened
                messages.append({"role": "assistant", "content": raw_response})
                messages.append({"role": "user", "content": f"OBSERVATION:\n{observation}"})
                continue

            # Case C: Unknown action — ask agent to try again
            messages.append({"role": "assistant", "content": raw_response})
            messages.append({"role": "user", "content": "ERROR: Invalid action. Use 'tool_call' or 'final_answer'."})

        # Max turns exhausted — return whatever we have
        return {
            "content": "I was unable to fully complete the analysis within the allowed steps.",
            "type": response_type,
            "results": last_results,
            "code": last_code,
            "chart_base64": last_chart_base64,
        }


# ============================================================
# Helper: format schema for the prompt
# ============================================================

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
) -> tuple:
    """
    Runs the requested tool and returns:
      (observation_string, raw_results_dict)

    The observation is what gets fed back to the agent.
    The raw_results is what gets returned to the frontend.
    """

    # --- SIMPLE tools: use AnalysisEngine ---
    if tool_name in {"aggregation", "filtering", "statistics", "correlation", "visualization"}:
        try:
            from app.analysis_engine import AnalysisEngine

            # Build the execution plan in the format AnalysisEngine expects
            exec_plan = {}
            if tool_name == "aggregation":
                exec_plan["aggregation"] = parameters
            elif tool_name == "filtering":
                exec_plan["filters"] = parameters.get("filters", [])
            elif tool_name == "statistics":
                exec_plan["statistics"] = parameters
            elif tool_name == "correlation":
                exec_plan["correlation"] = True
                exec_plan["correlation_method"] = parameters.get("method", "pearson")
            elif tool_name == "visualization":
                exec_plan["visualization"] = parameters

            results = AnalysisEngine.execute_plan(db, dataset_id, exec_plan)

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
            import os
            import base64
            from app.sandbox.runner import SandboxRunner
            from app.services.dataset_manager import DatasetManager

            code = parameters.get("code", "")
            db_dataset = DatasetManager.get_dataset(db, dataset_id)
            if not db_dataset:
                return "ERROR: Dataset not found.", None

            run_result = SandboxRunner.run_code(dataset_id=dataset_id, python_code=code, project_id=project_id)

            # Read chart if generated
            chart_base64 = None
            if run_result.get("chart_path") and os.path.exists(run_result["chart_path"]):
                try:
                    with open(run_result["chart_path"], "rb") as f:
                        chart_base64 = base64.b64encode(f.read()).decode("utf-8")
                except Exception:
                    pass

            SandboxRunner.cleanup(run_result)

            if run_result.get("success"):
                stdout = run_result.get("stdout", "")
                variables = run_result.get("variables", {})
                observation = f"Code executed successfully.\nOutput:\n{stdout}"
                if variables:
                    observation += f"\nVariables: {json.dumps(variables, indent=2)}"
                return observation, {
                    "stdout": stdout,
                    "variables": variables,
                    "chart_base64": chart_base64,
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

    # Show first 5 rows as preview
    preview = data[:5]
    if preview:
        parts.append(f"Preview (first {len(preview)} rows):")
        for row in preview:
            parts.append(f"  {row}")

    if results.get("correlation"):
        parts.append(f"Correlation: {json.dumps(results['correlation'], indent=2)}")

    if results.get("visualization_blueprint"):
        parts.append(f"Chart blueprint: {json.dumps(results['visualization_blueprint'])}")

    parts.append("\nNow respond with your final_answer in valid JSON format.")
    return "\n".join(parts)
