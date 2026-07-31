import logging
from typing import Any, Dict
from app.llm.client import OllamaClient
from app.llm.prompts import INTERPRETER_SYSTEM_PROMPT, INTERPRETER_USER_TEMPLATE

logger = logging.getLogger(__name__)

class ResultInterpreter:
    @staticmethod
    def explain_results(user_query: str, raw_results: Any) -> str:
        """
        Interprets dataset query computation findings and returns user description.
        """
        # Truncate results if extremely long to avoid LLM context overflow
        results_str = str(raw_results)
        if len(results_str) > 10000:
            results_str = results_str[:10000] + "\n... [TRUNCATED] ..."
            
        prompt = INTERPRETER_USER_TEMPLATE.format(
            user_query=user_query,
            raw_results=results_str
        )
        
        logger.info(f"Generating summary explanation for query: '{user_query}'")
        try:
            explanation = OllamaClient.call_model(
                prompt=prompt,
                system_prompt=INTERPRETER_SYSTEM_PROMPT
            )
            return explanation.strip()
        except Exception as e:
            logger.error(f"Interpretation request failed: {e}")
            return f"Calculated raw output results:\n{raw_results}"
