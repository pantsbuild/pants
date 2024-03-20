# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# On a Mac Mini M2 Pro, parsing the AST of all non-test python files (1184ish) and running in-place source-code replacements on 157 files takes < 1 second

from __future__ import annotations

import ast
from dataclasses import dataclass
import fileinput
import json
from pathlib import Path
import tokenize

@dataclass
class Replacement:
    line_range: tuple[int, int]
    col_range: tuple[int, int]
    current_source: str
    new_source: str
    new_imports: list[str]


with open("migrations.json", "r") as f:
    data = json.load(f)

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

# import pprint  
# pprint.pprint(lookup)

def map_no_args_get_to_new_syntax(get: ast.Call) -> str:
    """Get(<OutputType>) -> the_rule_to_call(**implicitly())"""
    # e.g. Call(func=Name(id='Get', ctx=Load()), args=[Name(id='Browser', ctx=Load())], keywords=[])
    assert len(get.args) == 1, f"Expected 1 arg, got {len(get.args)}"
    assert isinstance(get.args[0], ast.Name), f"Expected Name, got {get.args[0]}"
    key = (get.args[0].id,)
    new_function = lookup[key]
    return f"{new_function}(**implicitly())"
    
def map_long_form_get_to_new_syntax(get: ast.Call) -> tuple[str,list[str]]:
    """Get(<OutputType>, <InputType>, input) -> the_rule_to_call(**implicitly(input))"""
    # Call(func=Name(id='Get', ctx=Load()), 
    #   args=[
    #       Name(id='Browser', ctx=Load()), 
    #       Call(func=Name(id='BrowserRequest', ctx=Load()), args=[
    #           Call(func=Attribute(value=Name(id='request', ctx=Load()), attr='browser_request', ctx=Load()), args=[], keywords=[])], keywords=[])], keywords=[])
    assert len(get.args) == 3, f"Expected 3 arg, got {len(get.args)}"
    assert isinstance(get.args[0], ast.Name), f"Expected Name, got {get.args[0]}"
    assert isinstance(get.args[1], ast.Name), f"Expected Name, got {get.args[1]}"
    assert isinstance(get.args[2], ast.Call), f"Expected Call, got {get.args[2]}"
    key = (get.args[0].id, get.args[1].id)
    new_function, module = split_module_and_func(lookup[key])
    input_args = ast.unparse(get.args[2])

    return f"{new_function}(**implicitly({input_args}))", [f"from {module} import {new_function}"]


def map_get_to_new_syntax(get: ast.Call) -> Replacement:
    """There are 4 forms the old Get() syntax can take, so we can account for each one of them individually"""
    new_source: str | None = None
    imports: list[str] = []
    if len(get.args) == 1:
         new_source = map_no_args_get_to_new_syntax(get)
    elif len(get.args) == 3:
        new_source, imports = map_long_form_get_to_new_syntax(get)
    else:
        raise NotImplementedError(f"get: {get} not implemented")
    
    return Replacement(
        line_range=(get.lineno, get.end_lineno),
        col_range=(get.col_offset, get.end_col_offset),
        current_source=ast.unparse(get),
        new_source=new_source,
        new_imports=["from pants.engine.rules import implicitly", *imports]
    )

# From selectors.py: Get's can be created 4 ways, so need to handle each of them

# Call(func=Name(id='Get', ctx=Load()), args=[Name(id='Browser', ctx=Load()), Dict(keys=[Call(func=Attribute(value=Name(id='request', ctx=Load()), attr='browser_request', ctx=Load()), args=[], keywords=[])], values=[Name(id='BrowserRequest', ctx=Load())])], keywords=[])
    # + No arguments:
    #     
    # Is of the form:
    #   
    # And Becomes:
    #    the_rule_to_call(**implicitly())

    # + Long form:
    #     Get(<OutputType>, <InputType>, input)
    # Is of the form:
    #   Call(func=Name(id='Get', ctx=Load()), args=[Name(id='Browser', ctx=Load()), Name(id='BrowserRequest', ctx=Load()), Call(func=Attribute(value=Name(id='request', ctx=Load()), attr='browser_request', ctx=Load()), args=[], keywords=[])], keywords=[])
    # Becomes:
    #     the_rule_to_call(input)

    # + Short form
    #     Get(<OutputType>, <InputType>(<constructor args for input>))
    # Is of the form:
    #   Call(func=Name(id='Get', ctx=Load()), args=[Name(id='Browser', ctx=Load()), Call(func=Name(id='BrowserRequest', ctx=Load()), args=[Call(func=Attribute(value=Name(id='request', ctx=Load()), attr='browser_request', ctx=Load()), args=[], keywords=[])], keywords=[])], keywords=[])
    # Becomes:
    #     the_rule_to_call(input)

    # + Dict form
    #     Get(<OutputType>, {input1: <Input1Type>, ..inputN: <InputNType>})
    # Is of the form:
    #   Call(func=Name(id='Get', ctx=Load()), args=[Name(id='Browser', ctx=Load()), Dict(keys=[Call(func=Attribute(value=Name(id='request', ctx=Load()), attr='browser_request', ctx=Load()), args=[], keywords=[])], values=[Name(id='BrowserRequest', ctx=Load())])], keywords=[])
    # Becomes:
    #     the_rule_to_call(input1=input1, ..inputN=inputN)


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
                replacement = map_get_to_new_syntax(call)
                self.replacements.append(replacement)
                print(replacement)


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
        # print(f"Processing {file}")
        try:
            tree = ast.parse(f.read(), filename=file, type_comments=True)        
            visitor.visit(tree)            
        except SyntaxError as e:
            print(f"SyntaxError in {file}: {e}")
        except tokenize.TokenError as e:
            print(f"TokenError in {file}: {e}")
        # print("\n")
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
                    # print(line[:replacement.col_range[0]], end="")
                    # print(replacement.new_source)
                    # modified = True
                    modified = False
                elif line_number in range(replacement.line_range[0], replacement.line_range[1] + 1):
                    # If there are other lines in the range, just skip them
                    # modified = True
                    # TODO: Handle comments
                    modified = False
                    continue

            # For any lines that were not involved with replacements, emit them verbatim
            if not modified:
                print(line, end="")


# Recursive glob all python files, excluding *_test.py
files = Path().rglob("*.py")
for file in files:
    if "_test.py" in file.name:
        continue

    if not "graphql" in file.parent.name:
        continue

    if not "rules" in file.name:
        continue

    if replacements := create_replacements_for_file(file):
        perform_replacements_on_file(file, replacements)
