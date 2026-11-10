import os
import sys
import tempfile
import subprocess
import shutil
import json
import logging
from typing import Dict, Any, Tuple, Optional
from app.core.config import settings
from app.services.request_control import current_request, checkpoint, RequestStopped
from contextlib import nullcontext
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
    def run_code(dataset_id: str, python_code: str, project_id: Optional[str] = None, *, dataframe=None, chart_expectation=None, correlation_request=None) -> Dict[str, Any]:
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
            checkpoint()
            control = current_request.get()
            with subprocess.Popen(
                cmd,
                cwd=temp_dir,
                env={**os.environ, "PYTHONPATH": os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                preexec_fn=set_subprocess_resource_limits if os.name != "nt" else None
            ) as process:
                try:
                    with control.resource(process.kill) if control else nullcontext():
                        stdout_text, stderr_text = process.communicate(timeout=min(SANDBOX_TIMEOUT_SECONDS, control.remaining()) if control else SANDBOX_TIMEOUT_SECONDS)
                except BaseException:
                    process.kill()
                    process.communicate()
                    raise
                result = subprocess.CompletedProcess(cmd, process.returncode, stdout_text, stderr_text)
            checkpoint()

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
            structured_result = None
            verified_tables=[]
            if not error and result.returncode==0:
                from app.sandbox.structured_outputs import verify_exports
                exports_file=os.path.join(temp_dir,'analysis_tables.json')
                if os.path.isfile(exports_file):
                    try:
                        with open(exports_file) as manifest:exports=json.load(manifest)
                        if exports:
                            verification_frame=dataframe
                            if verification_frame is None:
                                import pandas as pd
                                if dataset_filepath.endswith('.csv'):verification_frame=pd.read_csv(dataset_filepath)
                                elif dataset_filepath.endswith('.json'):verification_frame=pd.read_json(dataset_filepath)
                                else:raise ValueError('Verified Python tables require the resolved input dataframe.')
                            verified_tables=verify_exports(exports,verification_frame)
                    except (ValueError,TypeError,KeyError) as invalid:error=str(invalid)
            if not error and result.returncode == 0 and correlation_request is not None:
                from app.analysis.correlation import validate_python_correlation
                try:
                    with open(os.path.join(temp_dir, 'correlations.json')) as manifest:
                        correlations = json.load(manifest)
                    structured_result = validate_python_correlation(correlations, dataframe, correlation_request)
                except (ValueError, OSError) as validation_error:
                    error = str(validation_error)
            if not error and result.returncode == 0 and chart_expectation:
                from app.analysis.chart_consistency import validate_captures
                capture_path = os.path.join(temp_dir, 'captures.json')
                captures = []
                if os.path.isfile(capture_path):
                    with open(capture_path) as manifest:
                        captures = json.load(manifest)
                try:
                    validate_captures(captures, chart_expectation)
                except ValueError as validation_error:
                    error = str(validation_error)
                else:
                    with open(capture_path,'w') as file: json.dump(captures,file)
            checkpoint()
            artifacts = persist_captures(temp_dir, project_id) if not error and result.returncode == 0 else []
            checkpoint()

            success = len(error) == 0 and result.returncode == 0
            
            return {
                "success": success,
                "stdout": stdout,
                "error": error if error else None,
                "variables": variables,
                "temp_dir": temp_dir,  # Return temp dir so caller can clean up
                "artifacts": artifacts,
                "results": structured_result,
                "verified_tables":verified_tables
            }

        except RequestStopped:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
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
