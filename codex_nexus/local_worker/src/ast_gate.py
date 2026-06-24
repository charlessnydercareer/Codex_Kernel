import ast
import os
import sys

def check_file_safety(file_path):
    """Scans a python file for prohibited AST patterns."""
    with open(file_path, "r") as source:
        try:
            tree = ast.parse(source.read())
        except SyntaxError:
            return False
            
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ['exec', 'eval']:
                print(f"[AST_GATE] Security Violation in {file_path}: {node.func.id}() calls are prohibited.")
                return False
        # Simplified the Import check so we don't block normal top-level imports
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '__import__':
            print(f"[AST_GATE] Security Violation in {file_path}: Dynamic __import__ is prohibited.")
            return False
            
    return True

def run_ast_gate(directory="src"):
    """Walks the src directory to validate all Python modules."""
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                if not check_file_safety(path):
                    sys.exit(1)
    
    print("[AST_GATE] Semantic scan passed: No prohibited patterns detected.")

if __name__ == "__main__":
    run_ast_gate()
