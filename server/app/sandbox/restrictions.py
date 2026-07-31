# Allowed modules for scientific/analytics computing inside the sandbox
ALLOWED_IMPORTS = {
    "pandas", "numpy", "matplotlib", "pyplot", "seaborn", "plotly", 
    "plotly.express", "plotly.graph_objects", "plotly.io",
    "scipy", "statistics", "math", "json"
}

# Modules that must be blocked at all costs
BLOCKED_IMPORTS = {
    "os", "sys", "subprocess", "socket", "requests", "urllib", "http",
    "shutil", "pathlib", "threading", "multiprocessing", "ctypes", "builtins",
    "importlib", "pickle", "marshal", "shelve", "dbm", "sqlite3"
}

# Forbidden Python built-in functions
BLOCKED_BUILTINS = {
    "eval", "exec", "open", "compile", "globals", "locals", "getattr", "setattr", "delattr"
}
