# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# On a Mac Mini M2 Pro, parsing the AST of all non-test python files (1184ish) and running in-place source-code replacements on 157 files takes < 1 second

# TODO: Prepare for move to the migrate_call_by_name.py goal
# TODO: Pull more functionality into the Visitor, so it's easier to port over
# TODO: Write some AST tests for the Visitor
# TODO: Split out "script" functionality, against what will be "Goal" functionality
# TODO: Handle comments nested in Call (which is horrifically annoying)
# TODO: setup_pytest_for_target is underspecified, keeps trying to pull in the junit version
# TODO: Don't try to fix shadowing if the name is in the current file


from __future__ import annotations

import ast
from dataclasses import dataclass
import fileinput
import json
import logging
from pathlib import Path
import tokenize
from typing import TypedDict

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# Copied/Pasted from migrate_call_by_name.py - as the Visitor will eventually be there anyways
class RuleGraphGet(TypedDict):
    function: str
    gets: list[RuleGraphGetDep]

class RuleGraphGetDep(TypedDict):
    input_types: list[str]
    output_type: str
    rule_dep: str

@dataclass
class Replacement:
    line_range: tuple[int, int]
    col_range: tuple[int, int]
    current_source: ast.Call
    new_source: ast.Call
    additional_imports: list[ast.ImportFrom]


with open("migrations.json", "r") as f:
    data: list[RuleGraphGet] = json.load(f)

def removed_module_prefix(s: str) -> str:
    return s.split(".")[-1]

def split_module_and_func(s: str) -> tuple[str, str]:
    """Split the module and function name from a string of the form `module.function`"""
    parts = s.split(".")
    return parts[-1], ".".join(parts[:-1])

# The goal is to make a lookup using the output type, and inputs as the key, and the rule_dep as the value
lookup: dict[tuple[str, ...], str] = {}
for item in data:
    for get in item["gets"]:
        output_type = removed_module_prefix(get["output_type"])
        input_types = [removed_module_prefix(input_type) for input_type in get["input_types"]]
        key = (output_type, *tuple(input_types))
        # key = (get["output_type"].split(".")[-1], *tuple(get["input_types"]))
        value = get["rule_dep"]
        if key in lookup:
            assert f"Duplicate key found in lookup table! {key}"
        lookup[key] = value

def map_no_args_get_to_new_syntax(get: ast.Call) -> tuple[ast.Call, list[ast.ImportFrom]]:
    """Get(<OutputType>) -> the_rule_to_call(**implicitly())"""

    logging.debug(ast.dump(get))
    assert len(get.args) == 1, f"Expected 1 arg, got {len(get.args)}"
    assert isinstance(output_type := get.args[0], ast.Name), f"Expected Name, got {get.args[0]}"

    new_function, module = split_module_and_func(lookup[(output_type.id,)])

    new_call = ast.Call(
        func=ast.Name(id=new_function), 
        args=[],
        keywords=[ast.keyword(value=ast.Call(func=ast.Name(id="implicitly"), args=[], keywords=[]))]
    )
    imports = [ast.ImportFrom(module, names=[ast.alias(new_function)])]
    return new_call, imports
    
def map_long_form_get_to_new_syntax(get: ast.Call) -> tuple[ast.Call, list[ast.ImportFrom]]:
    """Get(<OutputType>, <InputType>, input) -> the_rule_to_call(**implicitly(input))"""

    logging.debug(ast.dump(get))
    assert len(get.args) == 3, f"Expected 3 arg, got {len(get.args)}"
    assert isinstance(output_type := get.args[0], ast.Name), f"Expected Name, got {get.args[0]}"
    assert isinstance(input_type := get.args[1], ast.Name), f"Expected Name, got {get.args[1]}"
    
    key = (output_type.id, input_type.id)
    new_function, module = split_module_and_func(lookup[key])
    # input_args = ast.unparse(get.args[2])

    new_call = ast.Call(
        func=ast.Name(id=new_function),
        args=[],
        keywords=[ast.keyword(value=ast.Call(
            func=ast.Name(id="implicitly"), 
            args=[ast.Dict(keys=[get.args[2]], values=[ast.Name(id=input_type.id)])], 
            keywords=[]
        ))]
    )
    imports = [ast.ImportFrom(module, names=[ast.alias(new_function)])]
    return new_call, imports

def map_short_form_get_to_new_syntax(get: ast.Call) -> tuple[ast.Call, list[ast.ImportFrom]]:
    """Get(<OutputType>, <InputType>(<constructor args for input>)) -> the_rule_to_call(**implicitly(input))"""

    logging.debug(ast.dump(get))
    assert len(get.args) == 2, f"Expected 2 arg, got {len(get.args)}"
    assert isinstance(output_type := get.args[0], ast.Name), f"Expected Name, got {get.args[0]}"
    assert isinstance(input_call := get.args[1], ast.Call), f"Expected Call, got {get.args[1]}"
    assert isinstance(input_type := input_call.func, ast.Name), f"Expected Name, got {input_call.func}"
    key = (output_type.id, input_type.id)
    new_function, module = split_module_and_func(lookup[key])
    # input_args = ast.unparse(get.args[1])

    new_call = ast.Call(
        func=ast.Name(id=new_function),
        args=[],
        keywords=[ast.keyword(value=ast.Call(
            func=ast.Name(id="implicitly"), 
            args=[input_call], 
            keywords=[]
        ))]
    )
    imports = [ast.ImportFrom(module, names=[ast.alias(new_function)])]
    return new_call, imports

def map_dict_form_get_to_new_syntax(get: ast.Call) -> tuple[ast.Call, list[ast.ImportFrom]]:
    """Get(<OutputType>, {input1: <Input1Type>, ..inputN: <InputNType>}) -> the_rule_to_call(**implicitly(input))"""

    logging.debug(ast.dump(get))
    assert len(get.args) == 2, f"Expected 2 arg, got {len(get.args)}"
    assert isinstance(output_type := get.args[0], ast.Name), f"Expected Name, got {get.args[0]}"
    assert isinstance(input_dict := get.args[1], ast.Dict), f"Expected Dict, got {get.args[1]}"
    key = (output_type.id, *input_dict.keys)
    new_function, module = split_module_and_func(lookup[key])
    # input_args = ast.unparse(get.args[1])

    new_call = ast.Call(
        func=ast.Name(id=new_function),
        args=[],
        keywords=[ast.keyword(value=ast.Call(
            func=ast.Name(id="implicitly"), 
            args=[input_dict], 
            keywords=[]
        ))]
    )
    imports = [ast.ImportFrom(module, names=[ast.alias(new_function)])]
    return new_call, imports

total = 0
not_migrated = 0

def map_get_to_new_syntax(get: ast.Call) -> Replacement | None:
    """There are 4 forms the old Get() syntax can take, so we can account for each one of them individually"""
    new_source: ast.Call | None = None
    imports: list[ast.ImportFrom] = []

    global total
    global not_migrated

    total += 1
    try:
        if len(get.args) == 1:
            new_source, imports = map_no_args_get_to_new_syntax(get)
        elif len(get.args) == 2 and isinstance(get.args[1], ast.Call):
            new_source, imports = map_short_form_get_to_new_syntax(get)
        elif len(get.args) == 2 and isinstance(get.args[1], ast.Dict):
            new_source, imports = map_dict_form_get_to_new_syntax(get)
        elif len(get.args) == 3:
            new_source, imports = map_long_form_get_to_new_syntax(get)
        else:
            raise NotImplementedError(f"get: {get} not implemented")
    except NotImplementedError as e:
        not_migrated += 1
        logging.warning(f"Failed to migrate {ast.unparse(get)} as it's not implemented\n")
        return None
    except AssertionError as e:
        not_migrated += 1
        logging.warning(f"Failed to migrate {ast.unparse(get)} with assertion error {e}\n")
        return None
    except KeyError as e:
        not_migrated += 1
        logging.warning(f"Failed to migrate {ast.unparse(get)} due to lookup error {e}\n")
        return None
    except Exception as e:
        not_migrated += 1
        logging.warning(f"Failed to migrate {ast.unparse(get)} with {e}\n")
        return None
    
    return Replacement(
        line_range=(get.lineno, get.end_lineno),
        col_range=(get.col_offset, get.end_col_offset),
        current_source=get,
        new_source=new_source,
        additional_imports=[ast.ImportFrom(module="pants.engine.rules", names=[ast.alias("implicitly")]), *imports]
    )

class CallByNameVisitor(ast.NodeVisitor):
   
    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()
        self.replacements: list[Replacement] = []

    def visit_Name(self, node: ast.Name):
        """Collect all names in the file, so we can avoid shadowing them with the new imports"""
        self.names.add(node.id)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Replace the Get() calls with a call-by-name equivalent syntax in @rule decorated async functions.

        The replacement code comes from the Rust rule graph implementation, and for the purpose of this script, 
        it's assumed to be a lookup table as an array of items hashed against the function name of interest.

        TODO: Should we even check for rules? Or just lookup the function name in the lookup (probably equally fast, or irrelevantly fast)

        In each file we do a replacement, we should add an import to the top of the file to reference the call-by-name'd function.
        We should also add an import to "implicitly", as we'll likely use it in the call-by-name'd function params.
        """
        
        # Ensure we collect all names in this function, as well
        names = [n.id for n in ast.walk(node) if isinstance(n, ast.Name)]
        self.names.update(names)

        if not self._should_visit_node(node.decorator_list):
            return
    
        # In the body, look for `await Get`, and replace it with a call-by-name equivalent
        for child in node.body:
            if call := self._maybe_replaceable_call(child):
                if replacement := map_get_to_new_syntax(call):
                    self.replacements.append(replacement)


    def _should_visit_node(self, decorator_list: list[ast.expr]) -> bool:
        """Only interested in async functions with the @rule(...) decorator"""
        for decorator in decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "rule":
                # Accounts for "@rule"
                return True
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name) and decorator.func.id == "rule":
                # Accounts for "@rule(desc=..., level=...)"
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
        logging.info(f"Processing {file}")
        try:
            tree = ast.parse(f.read(), filename=file, type_comments=True)        
            visitor.visit(tree)            
        except SyntaxError as e:
            logging.error(f"SyntaxError in {file}: {e}")
        except tokenize.TokenError as e:
            logging.error(f"TokenError in {file}: {e}")
        logging.info("\n")
    
    names = visitor.names
    # Sanitize the replacements, so we don't shadow any existing names
    for replacement in visitor.replacements:
        assert isinstance(replacement.new_source.func, ast.Name)
        func_name = replacement.new_source.func.id
        if func_name in names:
            bound_name = f"{func_name}_get"
            replacement.new_source.func.id = bound_name
            for i in replacement.additional_imports:
                if i.names[0].name == func_name:
                    i.names[0].asname = bound_name
            logging.warning(f"Renamed {func_name} to {bound_name} to avoid shadowing")
    return visitor.replacements

def perform_replacements_on_file(file: Path, replacements: list[Replacement]):
    """In-place replacements for the new source code in a file"""
    
    # src/python/pants/core/subsystems/python_bootstrap.py --> src.python.pants.core.subsystems.python_bootstrap
    naive_module_name = str(file.with_suffix("")).replace("/", ".")

    imports_added = False
    import_strings: set[str] = set()
    for replacement in replacements:
        for i in replacement.additional_imports:
            assert i.module is not None
            if naive_module_name.endswith(i.module):
                # Don't import the module we're in, avoiding circular imports
                continue

            import_strings.add(ast.unparse(i))
        
    
    with fileinput.input(file, inplace=True) as f:
        for line in f:
            line_number = f.lineno()

            modified = False
            for replacement in replacements:
                if line_number == replacement.line_range[0]:
                    # On the first line of the range, emit the new source code where the old code started
                    print(line[:replacement.col_range[0]], end="")
                    print(ast.unparse(replacement.new_source))
                    modified = True
                    # modified = False
                elif line_number in range(replacement.line_range[0], replacement.line_range[1] + 1):
                    # If there are other lines in the range, just skip them
                    modified = True
                    # TODO: Handle comments
                    # modified = False
                    continue

            # For any lines that were not involved with replacements, emit them verbatim
            if not modified:
                print(line, end="")

            # Add the below "pants.engine.rules"
            # Note: Intentionally not trying to add to the existing "pants.engine.rules" import, as merging and unparsing would wipe out comments (if any)
            # Instead, add a new import and let the formatters sort it out
            if not imports_added and line.startswith("from pants.engine.rules"):
                print("\n".join(import_strings))
                imports_added = True


# Recursive glob all python files, excluding *_test.py
files = Path().rglob("*.py")
for file in files:
    if "_test.py" in file.name:
        continue

    rel_file = file.absolute().relative_to(file.cwd())
    if "internals" in rel_file.parts:
        # There are some circular imports in graph.py, that can't be resolved here
        continue
    
    if "backend/python/" not in str(rel_file):
        continue

    if replacements := create_replacements_for_file(rel_file):
        perform_replacements_on_file(rel_file, replacements)

logging.info(f"Total: {total}, Not Migrated: {not_migrated}")
