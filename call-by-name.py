import ast
from pathlib import Path
import tokenize

# Recursively iterate through all python files and run ast.parse on each of them
# On a Mac Mini M2 Pro, parsing the AST of all python files (1650ish) is < 1 second (transforming/visiting adds time)

class CallByNameMigrator(ast.NodeTransformer):
   
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
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
            call = self._maybe_replaceable_call(child)
            if call:
                print(ast.dump(call))
                
                new_call = self._replace_statement(call)
                print(ast.dump(new_call))
                
                # Replace the existing call with the new call 
                child.value.value.value = new_call

        
        return node

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
    
    def _replace_statement(self, statement: ast.Call) -> ast.Call:
        """Append a TODO comment to the end of the statement"""
        
        statement.func = ast.Name(
            id="call_by_some_name"
        )
        return statement

# Recursive glob all python files, excluding *_test.py
# transformer = Visitor()
files = Path().rglob("*.py")
for file in files:
    if "_test.py" in file.name:
        continue
    if "graphql" not in file.parent.name:
        continue

    if "rules" not in file.name:
        continue
    with open(file, "rb") as f:
        print(f"Processing {file}")
        try:
            tree = ast.parse(f.read(), filename=file, type_comments=True)

            migrator = CallByNameMigrator()
            # Apply the transformer to the AST
            migrated_tree = migrator.visit(tree)
            # Convert the transformed AST back to code
            transformed_code = ast.unparse(migrated_tree)
            
            print(transformed_code)
            
            # print(ast.dump(tree, include_attributes=False, indent=2))

            # break
        except SyntaxError as e:
            print(f"SyntaxError in {file}: {e}")
        except tokenize.TokenError as e:
            print(f"TokenError in {file}: {e}")
        print("\n")
