import json
import urllib.request
import urllib.error
import logging
from typing import Dict, Any, Optional, List
from app.core.config import settings

logger = logging.getLogger(__name__)

class OllamaClient:
    @staticmethod
    def call_model(prompt: str, system_prompt: Optional[str] = None, json_format: bool = False) -> str:
        """
        Single-shot text generation using /api/generate.
        Used by the Planner and Interpreter (no conversation history needed).
        """
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
