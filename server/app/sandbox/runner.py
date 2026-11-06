import os
import sys
import tempfile
import subprocess
import shutil
import json
import logging
from typing import Dict, Any, Tuple, Optional
from app.core.config import settings
from app.core.constants import SANDBOX_TIMEOUT_SECONDS, SANDBOX_MAX_MEMORY_MB
from app.sandbox.validator import validate_code_safety

logger = logging.getLogger(__name__)

# System resource limits configuration (only available on Unix-like operating systems)
def set_subprocess_resource_limits():
    """
    Applies CPU and memory limits inside the child subprocess.
    """
    try:
        import resource
        # Convert MB to bytes
        mem_limit_bytes = SANDBOX_MAX_MEMORY_MB * 1024 * 1024
        # Set memory ceiling limits
        resource.setrlimit(resource.RLIMIT_AS, (mem_limit_bytes, mem_limit_bytes))
    except (ImportError, Exception) as e:
        logger.warning(f"Resource constraints module not available or failed: {e}")

class SandboxRunner:
    @staticmethod
    def _resolve_dataset_path(dataset_id: str) -> str:
        """
        Resolves dataset_id against settings.DATASETS_DIR with strict path traversal validation.
        """
        filename = os.path.basename(dataset_id)
        if filename != dataset_id or ".." in dataset_id or "/" in dataset_id or "\\" in dataset_id:
            # If full valid path inside DATASETS_DIR was passed, allow if safe
            abs_input = os.path.abspath(dataset_id)
            datasets_dir_abs = os.path.abspath(settings.DATASETS_DIR)
            if abs_input.startswith(datasets_dir_abs) and os.path.exists(abs_input):
                return abs_input
            raise ValueError(f"Path traversal check failed or invalid dataset_id: {dataset_id}")

        target_path = os.path.abspath(os.path.join(settings.DATASETS_DIR, filename))
        datasets_dir_abs = os.path.abspath(settings.DATASETS_DIR)
        if not target_path.startswith(datasets_dir_abs):
            raise ValueError("Dataset path traversal security check failed.")
            
        if not os.path.exists(target_path):
            raise FileNotFoundError(f"Dataset '{filename}' not found in catalog.")
            
        return target_path

    @staticmethod
    def run_code(dataset_id: str, python_code: str, project_id: Optional[str] = None, *, dataframe=None) -> Dict[str, Any]:
        """
        Validates python_code and executes it in an isolated subprocess.
        Returns execution results including stdout, error trace, and generated plot paths.
        """
        # 1. Run security check
        is_safe, security_errors = validate_code_safety(python_code)
        if not is_safe:
            return {
                "success": False,
                "error": f"Security validation failed: {', '.join(security_errors)}",
                "stdout": "",
                "variables": {}
            }

        # 2. Resolve dataset path safely
        try:
            dataset_filepath = SandboxRunner._resolve_dataset_path(dataset_id) if dataframe is None else None
        except Exception as resolve_err:
            return {
                "success": False,
                "error": f"Dataset resolution error: {resolve_err}",
                "stdout": "",
                "variables": {}
            }

        # 3. Initialize isolation workspace directories
        temp_dir = tempfile.mkdtemp(prefix="sandbox_run_")
        code_file_path = os.path.join(temp_dir, "user_script.py")
        
        try:
            if dataframe is not None:
                import sqlite3
                from contextlib import closing

                dataset_filepath = os.path.join(temp_dir, "analysis.db")
                with closing(sqlite3.connect(dataset_filepath)) as connection:
                    dataframe.to_sql("analysis", connection, index=False)

            # Write python script to execution environment
            with open(code_file_path, "w") as f:
                f.write(python_code)
                
            # Path to current virtual environment python executable or standard python3
            python_executable = sys.executable or "python3"
            executor_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "executor.py"))
            
            # Subprocess execution command parameters
            cmd = [
                python_executable,
                executor_path,
                "--data-path", dataset_filepath,
                "--code-file", code_file_path,
                "--output-dir", temp_dir
            ]
            
            # Start isolated process execution
            # preexec_fn sets resource limits in the subprocess (Linux only)
            result = subprocess.run(
                cmd,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=SANDBOX_TIMEOUT_SECONDS,
                preexec_fn=set_subprocess_resource_limits if os.name != "nt" else None
            )
            
            # 4. Read output results
            stdout = ""
            error = ""
            variables = {}
            
            stdout_file = os.path.join(temp_dir, "stdout.txt")
            if os.path.exists(stdout_file):
                with open(stdout_file, "r") as f:
                    stdout = f.read()
                    
            error_file = os.path.join(temp_dir, "error.txt")
            if os.path.exists(error_file):
                with open(error_file, "r") as f:
                    error = f.read()

            # Fallback to subprocess stderr if error file missing/empty but process failed
            if not error and result.returncode != 0 and result.stderr:
                error = result.stderr.strip()
                    
            vars_file = os.path.join(temp_dir, "variables.json")
            if os.path.exists(vars_file):
                try:
                    with open(vars_file, "r") as f:
                        variables = json.load(f)
                except Exception:
                    pass
                    
            from app.services.chart_artifacts import persist_captures
            artifacts = persist_captures(temp_dir, project_id) if not error and result.returncode == 0 else []

            success = len(error) == 0 and result.returncode == 0
            
            return {
                "success": success,
                "stdout": stdout,
                "error": error if error else None,
                "variables": variables,
                "temp_dir": temp_dir,  # Return temp dir so caller can clean up
                "artifacts": artifacts
            }

        except subprocess.TimeoutExpired:
            logger.warning(f"Execution timeout triggered after {SANDBOX_TIMEOUT_SECONDS}s.")
            return {
                "success": False,
                "error": f"Execution timed out. Code exceeded max limits of {SANDBOX_TIMEOUT_SECONDS} seconds.",
                "stdout": "",
                "variables": {}
            }
        except Exception as e:
            logger.error(f"Sandbox runner failed: {e}")
            return {
                "success": False,
                "error": f"Internal execution failure: {e}",
                "stdout": "",
                "variables": {}
            }
            
    @staticmethod
    def cleanup(run_results: Dict[str, Any]):
        """
        Removes temporary sandbox runner folder.
        """
        temp_dir = run_results.get("temp_dir")
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.debug(f"Cleaned up sandbox folder: {temp_dir}")
