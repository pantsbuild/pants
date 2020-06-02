# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import ast
from dataclasses import dataclass
from typing import Dict, Iterable

from pants.base.exceptions import ResolveError
from pants.engine.fs import Digest, FileContent, FilesContent, PathGlobs, Snapshot
from pants.engine.objects import Collection
from pants.engine.rules import rule
from pants.engine.selectors import Get, MultiGet


class LoadedSymbolsToExpose(Collection[str]):
    def __str__(self):
        return str([i for i in self])


@dataclass(frozen=True)
class LoadStatement:
    """A load statement is of the form: load("path/to/a:file.py", "symbol1", "symbol2"...)

    This will import "symbol1", "symbol2"... from file "path/to/a:file.py".

    Note: The syntax is inspired by Bazel's load statements:
        https://docs.bazel.build/versions/master/build-ref.html#load

    Note: Load statements are always evaluated before anything else in the file,
        so imported symbols can be reassigned.
    """

    path: str
    symbols_to_expose: LoadedSymbolsToExpose


class LoadStatements(Collection[LoadStatement]):
    pass


@dataclass(frozen=True)
class LoadStatementWithContent:
    path: str
    content: FileContent
    symbols_to_expose: LoadedSymbolsToExpose


@dataclass(frozen=True)
class BuildFilesWithLoads:
    map: Dict[FileContent, Collection[LoadStatementWithContent]]


@rule
async def snapshot_load_statement(statement: LoadStatement) -> LoadStatementWithContent:
    snapshot = await Get[Snapshot](PathGlobs(globs=(statement.path,)))
    files_content = await Get[FilesContent](Digest, snapshot.directory_digest)
    file_content_list = [fc for fc in files_content]
    if len(file_content_list) != 1:
        raise ResolveError(f'Tried to load non existing file: "{statement.path}"')
    file_content = file_content_list[0]
    return LoadStatementWithContent(
        path=statement.path, content=file_content, symbols_to_expose=statement.symbols_to_expose
    )


@rule
async def parse_build_file_for_load_statements(content: FileContent) -> LoadStatements:
    class LoadParser(ast.NodeVisitor):
        """A utility class that parses load() calls in BUILD files."""

        def __init__(self):
            self.loads: list[LoadStatement] = []

        def _path_from_label(self, label):
            if label[0:2] == "//":
                label = f"{label[2:]}"
            label = label.replace(":", "/")
            return label

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name):
                if node.func.id == "load":
                    strargs = [arg.s for arg in node.args]
                    source_file = self._path_from_label(strargs[0])
                    exposed_symbols = strargs[1:]
                    self.loads.append(
                        LoadStatement(source_file, LoadedSymbolsToExpose(exposed_symbols))
                    )

        @staticmethod
        def parse_loads(python_code: str) -> Iterable[LoadStatement]:
            """Parse the python code searching for load statements."""
            load_parser = LoadParser()
            parsed = ast.parse(python_code)
            load_parser.visit(parsed)
            return load_parser.loads

    return LoadStatements(LoadParser.parse_loads(content.content.decode()))


@rule
async def load_symbols(build_file_contents: FilesContent) -> BuildFilesWithLoads:
    build_files_with_loads = {}
    for build_file in build_file_contents:
        load_statements = await Get[LoadStatements](FileContent, build_file)
        load_statements_with_content = await MultiGet(
            Get[LoadStatementWithContent](LoadStatement, load_statement)
            for load_statement in load_statements
        )

        build_files_with_loads[build_file] = Collection(load_statements_with_content)

    return BuildFilesWithLoads(build_files_with_loads)
