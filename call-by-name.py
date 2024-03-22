# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# On a Mac Mini M2 Pro, parsing the AST of all non-test python files (1184ish) and running in-place source-code replacements on 157 files takes < 1 second

# TODO: Prepare for move to the migrate_call_by_name.py goal
# TODO: Pull more functionality into the Visitor, so it's easier to port over
# TODO: Write some AST tests for the Visitor
# TODO: Handle comments nested in Call (which is horrifically annoying)
# TODO: setup_pytest_for_target is underspecified, keeps trying to pull in the junit version
# TODO: Don't try to fix shadowing if the name is in the current file

from __future__ import annotations

import ast
from dataclasses import dataclass
import fileinput
import json
import logging
from pathlib import Path, PurePath
import tokenize
from typing import TypedDict

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# Copied/Pasted from migrate_call_by_name.py - as the Visitor will eventually be there anyways
class RuleGraphGet(TypedDict):
    filepath: str
    function: str
    module: str
    gets: list[RuleGraphGetDep]

class RuleGraphGetDep(TypedDict):
    input_types: list[RuleType]
    output_type: RuleType
    rule_dep: RuleFunction

class RuleType(TypedDict):
    module: str
    name: str

class RuleFunction(TypedDict):
    function: str
    module: str

@dataclass
class Replacement:
    filename: PurePath
    module: str
    line_range: tuple[int, int]
    col_range: tuple[int, int]
    current_source: ast.Call
    new_source: ast.Call
    additional_imports: list[ast.ImportFrom]

    def sanitized_imports(self) -> list[ast.ImportFrom]:
        """Remove any circular or self-imports"""
        return [i for i in self.additional_imports if i.module != self.module]

    def sanitize(self, names: set[str]):
        """Remove any shadowing of names"""
        assert isinstance(self.new_source.func, ast.Name)
        func_name = self.new_source.func.id
        if func_name in names:
            bound_name = f"{func_name}_get"
            self.new_source.func.id = bound_name
            for i in self.additional_imports:
                if i.names[0].name == func_name:
                    i.names[0].asname = bound_name
            logging.warning(f"Renamed {func_name} to {bound_name} to avoid shadowing")
        

    def __str__(self) -> str:
        return f"Replacement: {ast.unparse(self.current_source)} -> {ast.unparse(self.new_source)}"


class CallByNameSyntaxMapper:
    def __init__(self, graphs: list[RuleGraphGet]) -> None:
        self.graphs = graphs
        
    def map_get_to_new_syntax(self, get: ast.Call, filename: PurePath, calling_func: str) -> Replacement | None:
        """There are 4 forms the old Get() syntax can take, so we can account for each one of them individually"""
        new_source: ast.Call | None = None
        imports: list[ast.ImportFrom] = []

        graph_item = next((item for item in self.graphs if item["filepath"] == str(filename) and item["function"] == calling_func), None)
        if not graph_item:
            logger.warning(f"Failed to find dependencies for {filename} {calling_func}")
            return None
        
        get_deps = graph_item["gets"]
        
        try:
            if len(get.args) == 1:
                new_source, imports = self.map_no_args_get_to_new_syntax(get, get_deps)
            elif len(get.args) == 2 and isinstance(get.args[1], ast.Call):
                new_source, imports = self.map_short_form_get_to_new_syntax(get, get_deps)
            elif len(get.args) == 2 and isinstance(get.args[1], ast.Dict):
                new_source, imports = self.map_dict_form_get_to_new_syntax(get, get_deps)
            elif len(get.args) == 3:
                new_source, imports = self.map_long_form_get_to_new_syntax(get, get_deps)
            else:
                raise NotImplementedError(f"get: {get} not implemented")
        except NotImplementedError as e:
            logging.warning(f"Failed to migrate {ast.unparse(get)} as it's not implemented\n")
            return None
        except AssertionError as e:
            logging.warning(f"Failed to migrate {ast.unparse(get)} with assertion error {e}\n")
            return None
        except KeyError as e:
            logging.warning(f"Failed to migrate {ast.unparse(get)} due to lookup error {e}\n")
            return None
        except Exception as e:
            logging.warning(f"Failed to migrate {ast.unparse(get)} with {e}\n")
            return None
        
        assert get.end_lineno is not None
        assert get.end_col_offset is not None
        return Replacement(
            filename=filename,
            module=graph_item["module"],
            line_range=(get.lineno, get.end_lineno),
            col_range=(get.col_offset, get.end_col_offset),
            current_source=get,
            new_source=new_source,
            additional_imports=[ast.ImportFrom(module="pants.engine.rules", names=[ast.alias("implicitly")]), *imports]
        )

    def map_no_args_get_to_new_syntax(self, get: ast.Call, deps: list[RuleGraphGetDep]) -> tuple[ast.Call, list[ast.ImportFrom]]:
        """Get(<OutputType>) -> the_rule_to_call(**implicitly())"""

        logging.debug(ast.dump(get))
        assert len(get.args) == 1, f"Expected 1 arg, got {len(get.args)}"
        assert isinstance(output_type := get.args[0], ast.Name), f"Expected Name, got {get.args[0]}"

        dep = next(dep for dep in deps if dep["output_type"]["name"] == output_type.id and not dep["input_types"])
        module = dep["rule_dep"]["module"]
        new_function = dep["rule_dep"]["function"]

        new_call = ast.Call(
            func=ast.Name(id=new_function), 
            args=[],
            keywords=[ast.keyword(value=ast.Call(func=ast.Name(id="implicitly"), args=[], keywords=[]))]
        )
        imports = [ast.ImportFrom(module, names=[ast.alias(new_function)])]
        return new_call, imports
        
    def map_long_form_get_to_new_syntax(self, get: ast.Call, deps: list[RuleGraphGetDep]) -> tuple[ast.Call, list[ast.ImportFrom]]:
        """Get(<OutputType>, <InputType>, input) -> the_rule_to_call(**implicitly(input))"""

        logging.debug(ast.dump(get))
        assert len(get.args) == 3, f"Expected 3 arg, got {len(get.args)}"
        assert isinstance(output_type := get.args[0], ast.Name), f"Expected Name, got {get.args[0]}"
        assert isinstance(input_type := get.args[1], ast.Name), f"Expected Name, got {get.args[1]}"
        
        dep = next(dep for dep in deps if dep["output_type"]["name"] == output_type.id and len(dep["input_types"]) == 1 and dep["input_types"][0]["name"] == input_type.id)
        module = dep["rule_dep"]["module"]
        new_function = dep["rule_dep"]["function"]

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

    def map_short_form_get_to_new_syntax(self, get: ast.Call, deps: list[RuleGraphGetDep]) -> tuple[ast.Call, list[ast.ImportFrom]]:
        """Get(<OutputType>, <InputType>(<constructor args for input>)) -> the_rule_to_call(**implicitly(input))"""

        logging.debug(ast.dump(get))
        assert len(get.args) == 2, f"Expected 2 arg, got {len(get.args)}"
        assert isinstance(output_type := get.args[0], ast.Name), f"Expected Name, got {get.args[0]}"
        assert isinstance(input_call := get.args[1], ast.Call), f"Expected Call, got {get.args[1]}"
        assert isinstance(input_type := input_call.func, ast.Name), f"Expected Name, got {input_call.func}"

        dep = next(dep for dep in deps if dep["output_type"]["name"] == output_type.id and len(dep["input_types"]) == 1 and dep["input_types"][0]["name"] == input_type.id)
        module = dep["rule_dep"]["module"]
        new_function = dep["rule_dep"]["function"]

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

    def map_dict_form_get_to_new_syntax(self, get: ast.Call, deps: list[RuleGraphGetDep]) -> tuple[ast.Call, list[ast.ImportFrom]]:
        """Get(<OutputType>, {input1: <Input1Type>, ..inputN: <InputNType>}) -> the_rule_to_call(**implicitly(input))"""

        logging.debug(ast.dump(get))
        assert len(get.args) == 2, f"Expected 2 arg, got {len(get.args)}"
        assert isinstance(output_type := get.args[0], ast.Name), f"Expected Name, got {get.args[0]}"
        assert isinstance(input_dict := get.args[1], ast.Dict), f"Expected Dict, got {get.args[1]}"

        d = next(dep for dep in deps if dep["output_type"].endswith(str(output_type.id)) and dep["input_types"] == list(input_dict.keys))
        module = dep["rule_dep"]["module"]
        new_function = dep["rule_dep"]["function"]

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

class CallByNameVisitor(ast.NodeVisitor):
   
    def __init__(self, filename: PurePath, syntax_mapper: CallByNameSyntaxMapper) -> None:
        super().__init__()

        self.filename = filename
        self.syntax_mapper = syntax_mapper
        self.names: set[str] = set()
        self.replacements: list[Replacement] = []

    def visit_Name(self, node: ast.Name):
        """Collect all names in the file, so we can avoid shadowing them with the new imports"""
        self.names.add(node.id)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Replace the Get() calls with a call-by-name equivalent syntax in @rule decorated async functions.

        The replacement code comes from the Rust rule graph implementation, and for the purpose of this script, 
        it's assumed to be a lookup table as an array of items hashed against the function name of interest.

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
                if replacement := self.syntax_mapper.map_get_to_new_syntax(call, self.filename, calling_func=node.name):
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

with open("migrations.json", "r") as f:
    graphs: list[RuleGraphGet] = json.load(f)

syntax_mapper = CallByNameSyntaxMapper(graphs)

def create_replacements_for_file(file: Path) -> list[Replacement]:
    visitor = CallByNameVisitor(file, syntax_mapper)
    with open(file, "rb") as f:
        logging.info(f"Processing {file}")
        try:
            tree = ast.parse(f.read(), filename=file, type_comments=True)        
            visitor.visit(tree)            
            print("\n")
        except SyntaxError as e:
            logging.error(f"SyntaxError in {file}: {e}")
        except tokenize.TokenError as e:
            logging.error(f"TokenError in {file}: {e}")
    
    names = visitor.names
    # Sanitize the replacements, so we don't shadow any existing names
    for replacement in visitor.replacements:
        replacement.sanitize(names)
    return visitor.replacements

def perform_replacements_on_file(file: Path, replacements: list[Replacement]):
    """In-place replacements for the new source code in a file"""

    imports_added = False
    import_strings: set[str] = set()
    for replacement in replacements:
        import_strings.update(ast.unparse(i) for i in replacement.sanitized_imports())
    
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
                    # Don't delete lines starting with comments
                    if line.lstrip().startswith("#"):
                        print(line, end="")
                    # If there are other lines in the range, just skip them
                    modified = True

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


# Grab list of files of interest from data["function"]

files = sorted(set(Path(f["filepath"]) for f in graphs))
for file in files:
    if "internals" in file.parts:
        # There are some circular imports in graph.py, that can't be resolved here
        continue

    if replacements := create_replacements_for_file(file):
        # perform_replacements_on_file(rel_file, replacements)
        pass
