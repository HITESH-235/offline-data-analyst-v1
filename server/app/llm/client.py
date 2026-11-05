import json
import urllib.request
import urllib.error
import logging
from typing import Dict, Any, Optional, List
from app.core.config import settings

logger = logging.getLogger(__name__)

class OllamaClient:
    @staticmethod
    def _openrouter_chat(messages, json_format: bool) -> str:
        key = settings.OPENROUTER_API_KEY.get_secret_value()
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is required for OpenRouter.")
        payload = {"model": settings.OPENROUTER_MODEL, "messages": messages}
        if json_format:
            payload["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"OpenRouter returned HTTP {error.code}.") from None
        except (urllib.error.URLError, TimeoutError):
            raise ConnectionError("Could not reach OpenRouter or the request timed out.") from None

        choices = result.get("choices") or []
        content = choices[0].get("message", {}).get("content") if choices else None
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenRouter returned no usable model response.")
        return content

    @staticmethod
    def call_model(prompt: str, system_prompt: Optional[str] = None, json_format: bool = False) -> str:
        """
        Single-shot text generation using /api/generate.
        Used by the Planner and Interpreter (no conversation history needed).
        """
        if settings.LLM_PROVIDER == "openrouter":
            messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
            messages.append({"role": "user", "content": prompt})
            return OllamaClient._openrouter_chat(messages, json_format)

        url = f"{settings.OLLAMA_BASE_URL}/api/generate"
        
        payload = {
            "model": settings.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }
        
        if system_prompt:
            payload["system"] = system_prompt
            
        if json_format:
            payload["format"] = "json"
            
        data = json.dumps(payload).encode("utf-8")
        
        req = urllib.request.Request(
            url, 
            data=data, 
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        try:
            with urllib.request.urlopen(req, timeout=600) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                return resp_data.get("response", "")
        except urllib.error.URLError as e:
            logger.error(f"Failed to connect to local Ollama server at {settings.OLLAMA_BASE_URL}: {e}")
            raise ConnectionError(
                f"Cannot contact local Ollama service. Ensure Ollama is running and '{settings.OLLAMA_MODEL}' model is installed. Error: {e}"
            )
        except Exception as e:
            logger.error(f"Ollama generation encountered an unexpected error: {e}")
            raise RuntimeError(f"Ollama service error: {e}")

    @staticmethod
    def call_model_chat(messages: List[Dict[str, str]], json_format: bool = False) -> str:
        """
        Multi-turn chat using /api/chat.
        Used by the Agent loop — accepts a full message history so the
        agent can see its prior actions and observations.

        messages format: [{"role": "system"|"user"|"assistant", "content": "..."}]
        """
        if settings.LLM_PROVIDER == "openrouter":
            return OllamaClient._openrouter_chat(messages, json_format)

        url = f"{settings.OLLAMA_BASE_URL}/api/chat"

        payload = {
            "model": settings.OLLAMA_MODEL,
            "messages": messages,
            "stream": False
        }

        if json_format:
            payload["format"] = "json"

        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=600) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                # /api/chat returns {"message": {"role": "assistant", "content": "..."}}
                return resp_data.get("message", {}).get("content", "")
        except urllib.error.URLError as e:
            logger.error(f"Failed to connect to local Ollama server at {settings.OLLAMA_BASE_URL}: {e}")
            raise ConnectionError(
                f"Cannot contact local Ollama service. Ensure Ollama is running and '{settings.OLLAMA_MODEL}' model is installed. Error: {e}"
            )
        except Exception as e:
            logger.error(f"Ollama chat encountered an unexpected error: {e}")
            raise RuntimeError(f"Ollama service error: {e}")
