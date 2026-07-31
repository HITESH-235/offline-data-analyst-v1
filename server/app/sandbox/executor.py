import sys
import os
import json
import argparse
import io
import pandas as pd

def run_isolated(data_path: str, code_content: str, output_dir: str):
    """
    Executes the user code in a restricted scope, saving results to output_dir.
    """
    # 1. Load dataset
    ext = data_path.split(".")[-1].lower()
    try:
        if ext == "csv":
            df = pd.read_csv(data_path)
        elif ext == "xlsx":
            df = pd.read_excel(data_path)
        elif ext == "json":
            df = pd.read_json(data_path)
        else:
            raise ValueError("Unsupported data format.")
    except Exception as e:
        with open(os.path.join(output_dir, "error.txt"), "w") as f:
            f.write(f"Failed to load dataset: {e}")
        return

    # 2. Redirect stdout
    stdout_buffer = io.StringIO()
    sys.stdout = stdout_buffer

    # 3. Restricted execution scope
    # Whitelist of modules/builtins available inside exec context
    import numpy as np
    import matplotlib.pyplot as plt
    import seaborn as sns
    import plotly.express as px
    import plotly.graph_objects as go

    # Override plt.show with a no-op to prevent GUI window hangs in sandbox
    plt.show = lambda *args, **kwargs: None

    # Prepare safe execution environment
    exec_globals = {
        "df": df,
        "pd": pd,
        "np": np,
        "plt": plt,
        "sns": sns,
        "px": px,
        "go": go,
        "print": print,
        # Allow standard mathematical functions
        "abs": abs, "round": round, "sum": sum, "min": min, "max": max, "len": len,
        "range": range, "list": list, "dict": dict, "set": set, "tuple": tuple,
        "str": str, "int": int, "float": float, "bool": bool, "zip": zip,
        "enumerate": enumerate, "any": any, "all": all
    }

    error_occurred = None
    try:
        # Run code
        exec(code_content, exec_globals)
        
        # 1. Capture Plotly figures if generated
        try:
            for var_name, var_val in exec_globals.items():
                if var_name in ["px", "go", "pio", "plt", "sns", "pd", "np"]:
                    continue
                if isinstance(var_val, go.Figure) or type(var_val).__name__ == "Figure":
                    plotly_html_path = os.path.join(output_dir, "output_chart.html")
                    var_val.write_html(plotly_html_path, include_plotlyjs="cdn")
                    break
        except Exception as plotly_err:
            stdout_buffer.write(f"\n[Warning: Failed to capture Plotly chart: {plotly_err}]")

        # 2. Save active matplotlib figure if generated
        try:
            if plt.get_fignums():
                chart_path = os.path.join(output_dir, "output_chart.png")
                plt.savefig(chart_path, bbox_inches="tight", dpi=150)
                plt.close("all")
        except Exception as plot_err:
            stdout_buffer.write(f"\n[Warning: Failed to capture Matplotlib plot: {plot_err}]")
            
    except Exception as e:
        error_occurred = str(e)
        import traceback
        with open(os.path.join(output_dir, "error.txt"), "w") as f:
            f.write(traceback.format_exc())

    # Restore stdout
    sys.stdout = sys.__stdout__

    # 4. Write stdout and execution variables
    with open(os.path.join(output_dir, "stdout.txt"), "w") as f:
        f.write(stdout_buffer.getvalue())

    # Write serialized variable outputs for state capture
    var_summary = {}
    for var_name, var_val in exec_globals.items():
        if var_name in ["df", "pd", "np", "plt", "sns", "px", "go", "exec_globals", "__builtins__"]:
            continue
            
        # Unpack numpy scalars to native python primitives
        val_to_check = var_val
        if hasattr(var_val, "item") and callable(getattr(var_val, "item")):
            try:
                val_to_check = var_val.item()
            except Exception:
                pass
                
        # Only serialize simple types
        if isinstance(val_to_check, (int, float, str, bool, list, dict)):
            try:
                # Test serialize
                json.dumps({var_name: val_to_check})
                var_summary[var_name] = val_to_check
            except Exception:
                continue

    with open(os.path.join(output_dir, "variables.json"), "w") as f:
        json.dump(var_summary, f, indent=4)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", required=True)
    parser.add_argument("--code-file", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    # Read user code
    with open(args.code_file, "r") as f:
        code_content = f.read()

    run_isolated(args.data_path, code_content, args.output_dir)
