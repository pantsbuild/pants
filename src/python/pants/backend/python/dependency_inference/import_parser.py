# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.util_rules.pex import PexInterpreterConstraints
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.collection import DeduplicatedCollection
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Sources
from pants.util.logging import LogLevel

_SCRIPT = """\
# -*- coding: utf-8 -*-

# NB: This must be compatible with Python 2.7 and 3.5+.

from __future__ import print_function, unicode_literals

from io import open
import ast
import os
import re
import sys

# This regex is used to infer imports from strings, e.g.
#  `importlib.import_module("example.subdir.Foo")`.
STRING_IMPORT_REGEX = re.compile(r"^([a-z_][a-z_\\d]*\\.){2,}[a-zA-Z_]\\w*$", re.UNICODE)

class AstVisitor(ast.NodeVisitor):
    def __init__(self, package_parts):
        self._package_parts = package_parts
        self.imports = set()

    def maybe_add_string_import(self, s):
        if STRING_IMPORT_REGEX.match(s):
            self.imports.add(s)

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.add(alias.name)

    def visit_ImportFrom(self, node):
        if node.level:
            # Relative import.
            rel_module = node.module
            abs_module = ".".join(
                self._package_parts[0 : len(self._package_parts) - node.level + 1]
                + ([] if rel_module is None else [rel_module])
            )
        else:
            abs_module = node.module
        for alias in node.names:
            self.imports.add("{}.{}".format(abs_module, alias.name))

    def visit_Call(self, node):
      # Handle __import__("string_literal").  This is commonly used in __init__.py files,
      # to explicitly mark namespace packages.  Note that we don't handle more complex
      # uses, such as those that set `level`.
      if (
          isinstance(node.func, ast.Name)
          and node.func.id == "__import__"
          and len(node.args) == 1
      ):
          if sys.version_info[0:2] < (3, 8) and isinstance(node.args[0], ast.Str):
              arg_s = node.args[0].s
              val = arg_s.decode("utf-8") if isinstance(arg_s, bytes) else arg_s
              self.imports.add(arg_s)
              return
          elif isinstance(node.args[0], ast.Constant):
              self.imports.add(str(node.args[0].value))
              return
      self.generic_visit(node)

if os.environ["STRING_IMPORTS"] == "y":
    # String handling changes a bit depending on Python version. We dynamically add the appropriate
    # logic.
    if sys.version_info[0:2] == (2,7):
        def visit_Str(self, node):
            try:
                val = node.s.decode("utf8") if isinstance(node.s, bytes) else node.s
                self.maybe_add_string_import(val)
            except UnicodeError:
                pass

        setattr(AstVisitor, 'visit_Str', visit_Str)

    elif sys.version_info[0:2] < (3, 8):
        def visit_Str(self, node):
            self.maybe_add_string_import(node.s)

        setattr(AstVisitor, 'visit_Str', visit_Str)

    else:
        def visit_Constant(self, node):
            if isinstance(node.value, str):
                self.maybe_add_string_import(node.value)

        setattr(AstVisitor, 'visit_Constant', visit_Constant)


def parse_file(filename):
    with open(filename, "rb") as f:
        content = f.read()
    try:
        return ast.parse(content, filename=filename)
    except SyntaxError:
        return None


if __name__ == "__main__":
    imports = set()

    for filename in sys.argv[1:]:
        tree = parse_file(filename)
        if not tree:
            continue

        package_parts = os.path.dirname(filename).split(os.path.sep)
        visitor = AstVisitor(package_parts)

        visitor.visit(tree)
        imports.update(visitor.imports)

    # We have to be careful to set the encoding explicitly and write raw bytes ourselves.
    # See below for where we explicitly decode.
    buffer = sys.stdout if sys.version_info[0:2] == (2, 7) else sys.stdout.buffer
    buffer.write("\\n".join(sorted(imports)).encode("utf8"))
"""


class ParsedPythonImports(DeduplicatedCollection[str]):
    """All the discovered imports from a Python source file.

    May include string imports if the request specified to include them.
    """


@dataclass(frozen=True)
class ParsePythonImportsRequest:
    sources: Sources
    interpreter_constraints: PexInterpreterConstraints
    string_imports: bool


@rule
async def parse_python_imports(request: ParsePythonImportsRequest) -> ParsedPythonImports:
    python_interpreter, script_digest, stripped_sources = await MultiGet(
        Get(PythonExecutable, PexInterpreterConstraints, request.interpreter_constraints),
        Get(Digest, CreateDigest([FileContent("__parse_python_imports.py", _SCRIPT.encode())])),
        Get(StrippedSourceFiles, SourceFilesRequest([request.sources])),
    )
    input_digest = await Get(
        Digest, MergeDigests([script_digest, stripped_sources.snapshot.digest])
    )
    process_result = await Get(
        ProcessResult,
        Process(
            argv=[
                python_interpreter.path,
                "./__parse_python_imports.py",
                *stripped_sources.snapshot.files,
            ],
            input_digest=input_digest,
            description=f"Determine Python imports for {request.sources.address}",
            env={"STRING_IMPORTS": "y" if request.string_imports else "n"},
            level=LogLevel.DEBUG,
        ),
    )
    # See above for where we explicitly encoded as utf8. Even though utf8 is the
    # default for decode(), we make that explicit here for emphasis.
    return ParsedPythonImports(process_result.stdout.decode("utf8").strip().splitlines())


def rules():
    return collect_rules()
