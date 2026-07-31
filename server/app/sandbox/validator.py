import ast # abstract syntax tree, python uses to execute the code
from typing import List, Tuple # for type hinting
from app.sandbox.restrictions import ALLOWED_IMPORTS, BLOCKED_IMPORTS, BLOCKED_BUILTINS # list of keywords we made in restrictions.py

class CodeSecurityValidator(ast.NodeVisitor): # inherits from class to visit each node in execution
    def __init__(self):
        self.errors: List[str] = []

    def visit_Import(self, node: ast.Import): # catches wrong imports
        for alias in node.names:
            base_module = alias.name.split(".")[0]
            if base_module in BLOCKED_IMPORTS:
                self.errors.append(f"Forbidden import: '{alias.name}'")
            elif base_module not in ALLOWED_IMPORTS:
                self.errors.append(f"Import '{alias.name}' is not allowed in V1 sandbox.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom): # catches wrong modules from an import
        if node.module:
            base_module = node.module.split(".")[0]
            if base_module in BLOCKED_IMPORTS:
                self.errors.append(f"Forbidden import from module: '{node.module}'")
            elif base_module not in ALLOWED_IMPORTS:
                self.errors.append(f"Import module '{node.module}' is not allowed in V1 sandbox.")
        self.generic_visit(node) # keeps digging to deeper nodes

    def visit_Call(self, node: ast.Call):
        # Prevent calling forbidden builtins like open(), eval(), exec()
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in BLOCKED_BUILTINS:
                self.errors.append(f"Call to blocked built-in function: '{func_name}'")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        # Prevent accessing double-underscore variables/magic attributes to escape sandbox (dunder attr)
        if node.attr.startswith("__") or node.attr.endswith("__"):
            self.errors.append(f"Access to private/magic attribute is blocked: '{node.attr}'")
        self.generic_visit(node)

def validate_code_safety(code: str) -> Tuple[bool, List[str]]:
    """
    Parses code using AST and scans for import blacklists and magic call properties.
    Returns (is_safe, list_of_errors).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, [f"Syntax error: {e}"]
        
    validator = CodeSecurityValidator()
    validator.visit(tree)
    
    if validator.errors: # if error list isnt empty
        return False, validator.errors
    return True, []
