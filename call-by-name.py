# On a Mac Mini M2 Pro, parsing the AST of all non-test python files (1184ish) and running in-place source-code replacements on 157 files takes < 1 second

import ast
from dataclasses import dataclass
import fileinput
from pathlib import Path
import tokenize

@dataclass
class Replacement:
    line_range: tuple[int, int]
    col_range: tuple[int, int]
    current_source: str
    new_source: str

class CallByNameVisitor(ast.NodeVisitor):
   
    def __init__(self) -> None:
        super().__init__()
        self.replacements: list[Replacement] = []

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Replace the Get() calls with a call-by-name equivalent in @rule decorated async functions.

        The replacement code comes from the Rust rule graph implementation, and for the purpose of this script, 
        it's assumed to be a lookup table as an array of items hashed against the function name of interest.

        TODO: Should we even check for rules? Or just lookup the function name in the lookup (probably equally fast, or irrelevantly fast)

        In each file we do a replacement, we should add an import to the top of the file to reference the call-by-name'd function.
        We should also add an import to "implicitly", as we'll likely use it in the call-by-name'd function params.
        """
        if not self._should_visit_node(node.decorator_list):
            return node
            
        # In the body, look for `await Get`, and replace it with a call-by-name equivalent
        for child in node.body:
            if call := self._maybe_replaceable_call(child):
                self.replacements.append(
                    Replacement(
                        line_range=(call.lineno, call.end_lineno),
                        col_range=(call.col_offset, call.end_col_offset),
                        current_source=ast.unparse(call),
                        new_source="call_by_some_name(TODO TODO TODO)"
                    )
                )

    def _should_visit_node(self, decorator_list: list[ast.expr]) -> bool:
        """Only interested in async functions with the @rule decorator"""
        for decorator in decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "rule":
                return True
        return False
    
    def _maybe_replaceable_call(self, statement: ast.stmt) -> ast.Call | None:
        """Only interested in await Get() calls"""
        if (isinstance(statement, ast.Assign) 
            and isinstance((await_node := statement.value), ast.Await) 
            and isinstance((call_node  := await_node.value), ast.Call)
            and isinstance(call_node.func, ast.Name)
            and call_node.func.id == "Get"):
            return call_node
        return None


def create_replacements_for_file(file: Path) -> list[Replacement]:
    visitor = CallByNameVisitor()
    with open(file, "rb") as f:
        print(f"Processing {file}")
        try:
            tree = ast.parse(f.read(), filename=file, type_comments=True)        
            visitor.visit(tree)            
        except SyntaxError as e:
            print(f"SyntaxError in {file}: {e}")
        except tokenize.TokenError as e:
            print(f"TokenError in {file}: {e}")
        print("\n")
    return visitor.replacements

def perform_replacements_on_file(file: Path, replacements: list[Replacement]):
    """In-place replacements for the new source code in a file"""
    
    with fileinput.input(file, inplace=True) as f:
        for line in f:
            line_number = f.lineno()

            modified = False
            for replacement in replacements:
                if line_number == replacement.line_range[0]:
                    # On the first line of the range, emit the new source code where the old code started
                    print(line[:replacement.col_range[0]], end="")
                    print(replacement.new_source)
                    modified = True
                elif line_number in range(replacement.line_range[0], replacement.line_range[1] + 1):
                    # If there are other lines in the range, just skip them
                    modified = True
                    continue

            # For any lines that were not involved with replacements, emit them verbatim
            if not modified:
                print(line, end="")


# Recursive glob all python files, excluding *_test.py
files = Path().rglob("*.py")
for file in files:
    if "_test.py" in file.name:
        continue

    if replacements := create_replacements_for_file(file):
        perform_replacements_on_file(file, replacements)
