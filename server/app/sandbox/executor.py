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
        if data_path.endswith('.csv'):
            df = pd.read_csv(data_path)
        elif data_path.endswith('.xlsx'):
            df = pd.read_excel(data_path)
        elif data_path.endswith('.json'):
            df = pd.read_json(data_path)
        elif data_path.endswith('.db') or data_path.endswith('.sqlite'):
            import sqlite3
            conn = sqlite3.connect(data_path)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            tbls = [r[0] for r in cur.fetchall()]
            if tbls:
                target = "Orders" if "Orders" in tbls else tbls[0]
                df = pd.read_sql_query(f"SELECT * FROM \"{target}\"", conn)
            else:
                df = pd.DataFrame()
            conn.close()
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
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns
    import plotly.express as px
    import plotly.graph_objects as go

    correlation_captures = []
    original_corr = pd.DataFrame.corr
    def capture_correlation(frame, *args, **kwargs):
        matrix = original_corr(frame, *args, **kwargs)
        method = kwargs.get('method', args[0] if args else 'pearson')
        if method in ('pearson', 'spearman'):
            serializable = matrix.astype(object).where(pd.notna(matrix), None)
            correlation_captures.append({'columns': list(matrix.columns), 'matrix': serializable.values.tolist(),
                                         'method': method, 'source_observation_count': len(frame)})
        return matrix
    pd.DataFrame.corr = capture_correlation

    plt.rcParams.update({'figure.figsize': (11, 6), 'figure.dpi': 120, 'savefig.dpi': 180,
                         'figure.facecolor': 'white', 'axes.facecolor': 'white',
                         'text.color': '#14212B', 'axes.labelcolor': '#14212B',
                         'xtick.color': '#14212B', 'ytick.color': '#14212B',
                         'axes.prop_cycle': matplotlib.cycler(color=['#007D73', '#14212B', '#52616A']),
                         'font.size': 11, 'axes.spines.top': False, 'axes.spines.right': False})
    import plotly.io as pio
    palette = ['#007D73', '#14212B', '#637F8D', '#9A613C', '#69865B']
    pio.templates['analyst'] = go.layout.Template(layout={'colorway': palette, 'paper_bgcolor': '#FFFFFF',
        'plot_bgcolor': '#FFFFFF', 'font': {'family': 'system-ui, sans-serif', 'size': 12, 'color': '#14212B'}})
    pio.templates.default = 'analyst'
    px.defaults.template = 'analyst'
    px.defaults.color_discrete_sequence = palette
    from plotly.basedatatypes import BaseFigure
    captured_figures = []
    original_write_html = BaseFigure.write_html
    def capture_html(figure, file, *args, **kwargs):
        captured_figures.append(figure)
        kwargs['include_plotlyjs'] = True
        return original_write_html(figure, os.path.join(output_dir, os.path.basename(str(file))), **kwargs)
    BaseFigure.write_html = capture_html
    BaseFigure.show = lambda figure, *args, **kwargs: captured_figures.append(figure)

    # Record observations at plotting time; a raster image alone cannot prove its population.
    from matplotlib.axes import Axes
    from app.analysis.chart_consistency import population_summary
    histogram_observations = {}
    histogram_figures = {}
    original_hist = Axes.hist
    def record_hist(axis, x, *args, **kwargs):
        result = original_hist(axis, x, *args, **kwargs)
        try:
            array = np.asarray(x)
            groups = list(array.T) if isinstance(x, np.ndarray) and array.ndim == 2 else list(x) if array.ndim > 1 else [x]
        except (TypeError,ValueError):
            groups = list(x) if isinstance(x,(list,tuple)) else [x]
        for group in groups:
            try: summary = population_summary(group)
            except (TypeError,ValueError): summary = {'count':None,'fingerprint':None,'reason':'Observations could not be verified.'}
            summary['weighted'] = kwargs.get('weights') is not None or (len(args) > 3 and args[3] is not None)
            histogram_observations.setdefault(id(axis.figure), []).append(summary)
        histogram_figures[id(axis.figure)] = axis.figure
        return result
    Axes.hist = record_hist

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
        exports=[]
        declared=exec_globals.get('analysis_tables',{})
        plans=exec_globals.get('analysis_plans',{})
        if not isinstance(declared,dict) or not isinstance(plans,dict):raise ValueError('analysis_tables and analysis_plans must be dictionaries.')
        for ident,table in declared.items():
            if not isinstance(ident,str) or not isinstance(table,pd.DataFrame) or ident not in plans:raise ValueError('Each Python analysis table needs an ID, dataframe and canonical plan.')
            clean=table.astype(object).where(pd.notna(table),None)
            exports.append({'id':ident,'result':{'columns':list(table.columns),'data':clean.to_dict(orient='records'),'row_count':len(table)},'plan':plans[ident]})
        with open(os.path.join(output_dir,'analysis_tables.json'),'w') as output:
            json.dump(exports,output,allow_nan=False)
        
        captures = []
        figures = captured_figures + [value for value in exec_globals.values() if isinstance(value, BaseFigure)]
        seen = set()
        for index, figure in enumerate(figures):
            if id(figure) in seen:
                continue
            seen.add(id(figure))
            entry = {'kind': 'plotly', 'title': figure.layout.title.text or 'Generated chart', 'status': 'ready'}
            try:
                figure_name = f'figure_{index}.json'
                figure.write_json(os.path.join(output_dir, figure_name))
                entry['figure'] = figure_name
                histograms=[]
                for trace in figure.data:
                    if trace.type == 'histogram':
                        observed = trace.y if trace.orientation == 'h' else trace.x
                        summary = population_summary(observed if observed is not None else [])
                        summary['weighted'] = trace.histfunc not in (None,'count')
                        histograms.append(summary)
                if histograms: entry['observations'] = histograms
                point_types = {'scatter', 'scattergl', 'bar', 'histogram', 'box', 'violin'}
                empty_points = bool(figure.data) and all(
                    trace.type in point_types and all(getattr(trace, key, None) is None or len(getattr(trace, key)) == 0
                                                     for key in ('x', 'y', 'q1', 'median', 'q3'))
                    for trace in figure.data
                )
                if not figure.data or empty_points:
                    entry.update(status='empty', reason='The Python figure contains no plotted observations. Check filters and date parsing before treating it as an answer.')
            except Exception as capture_error:
                entry.update(status='download_only', reason=f'Figure capture failed: {capture_error}')
            try:
                export = f'figure_{index}.html'
                original_write_html(figure, os.path.join(output_dir, export), include_plotlyjs=True, full_html=True)
                entry['download'] = export
            except Exception as export_error:
                stdout_buffer.write(f'Chart export failed: {export_error}')
            captures.append(entry)

        matplotlib_figures = {id(plt.figure(number)):plt.figure(number) for number in plt.get_fignums()}
        matplotlib_figures.update(histogram_figures)
        for number, figure in enumerate(matplotlib_figures.values(),1):
            if not figure.axes:
                continue
            filename = f'matplotlib_{number}.png'
            try:
                figure.tight_layout()
                figure.savefig(os.path.join(output_dir, filename), bbox_inches='tight', dpi=max(180, figure.dpi))
                from PIL import Image
                with Image.open(os.path.join(output_dir, filename)) as image:
                    image_width, image_height = image.size
                captures.append({'kind': 'png', 'title': figure._suptitle.get_text() if figure._suptitle else figure.axes[0].get_title() or 'Generated image',
                                 'status': 'ready', 'download': filename,
                                 'width': image_width, 'height': image_height,
                                 'observations':histogram_observations.get(id(figure),[])})
            except Exception as capture_error:
                stdout_buffer.write(f'PNG capture failed: {capture_error}')
        plt.close('all')
        # Handle explicitly saved PNGs even when the original figure was closed.
        if not any(item['kind'] == 'png' for item in captures):
            from PIL import Image
            for filename in os.listdir(output_dir):
                if not filename.endswith('.png'):
                    continue
                path = os.path.join(output_dir, filename)
                with open(path, 'rb') as image:
                    valid_png = image.read(8) == bytes.fromhex('89504e470d0a1a0a')
                if valid_png:
                    with Image.open(path) as image:
                        image_width, image_height = image.size
                    captures.append({'kind': 'png', 'title': 'Generated image', 'status': 'ready',
                                     'download': filename, 'width': image_width, 'height': image_height})
        if not captures and os.path.isfile(os.path.join(output_dir, 'output_chart.html')):
            captures.append({'kind': 'html', 'title': 'Generated HTML chart', 'status': 'download_only',
                             'reason': 'No structured figure was captured. Download the HTML to inspect it separately.', 'download': 'output_chart.html'})
        with open(os.path.join(output_dir, 'captures.json'), 'w') as manifest:
            json.dump(captures, manifest)
        with open(os.path.join(output_dir, 'correlations.json'), 'w') as manifest:
            json.dump(correlation_captures, manifest, allow_nan=False)
            
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
