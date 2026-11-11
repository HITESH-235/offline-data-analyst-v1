import json
import urllib.request
import urllib.error
import logging
import http.client
import socket
from contextlib import contextmanager, ExitStack
from app.services.request_control import current_request, current_model_metadata, model_metadata
from app.llm.usage import report_usage
from typing import Dict, Any, Optional, List
from app.core.config import settings

logger = logging.getLogger(__name__)

@contextmanager
def provider_response(request, timeout):
    control = current_request.get()
    if control is None:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            yield response
        return
    with control.model_call(), ExitStack() as resources:
        def connection_type(base):
            class Connection(base):
                def connect(self):
                    super().connect()
                    sock = self.sock
                    def close():
                        try: sock.shutdown(socket.SHUT_RDWR)
                        except OSError: pass
                        sock.close()
                    resources.enter_context(control.resource(close))
            return Connection
        class HTTPHandler(urllib.request.HTTPHandler):
            def http_open(self, req):
                return self.do_open(connection_type(http.client.HTTPConnection), req)
        class HTTPSHandler(urllib.request.HTTPSHandler):
            def https_open(self, req):
                return self.do_open(connection_type(http.client.HTTPSConnection), req,
                                    context=self._context)
        opener = urllib.request.build_opener(HTTPHandler(), HTTPSHandler())
        # The socket timeout is also bounded; the supervisor handles dribbling bodies.
        with opener.open(request, timeout=min(timeout, control.remaining())) as response:
            yield response
        control.check()


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
            with model_metadata(provider='ollama', model=settings.OLLAMA_MODEL,
                                purpose=(current_model_metadata.get() or {}).get('purpose', 'generation'),
                                input_characters=len(prompt) + len(system_prompt or '')), provider_response(req, timeout=600) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                report_usage('ollama', resp_data)
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
            with model_metadata(provider='ollama', model=settings.OLLAMA_MODEL,
                                purpose=(current_model_metadata.get() or {}).get('purpose', 'agent_chat'),
                                input_characters=sum(len(m.get('content', '')) for m in messages)), provider_response(req, timeout=600) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                report_usage('ollama', resp_data)
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
