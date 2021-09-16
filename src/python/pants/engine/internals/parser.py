# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import ast
import os.path
import threading
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any, Iterable, NamedTuple

from pants.base.exceptions import MappingError
from pants.base.parse_context import ParseContext
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class BuildFilePreludeSymbols:
    symbols: FrozenDict[str, Any]


class ParseError(Exception):
    """Indicates an error parsing BUILD configuration."""


class UnaddressableObjectError(MappingError):
    """Indicates an un-addressable object was found at the top level."""


class ParseState(threading.local):
    def __init__(self):
        self._rel_path: str | None = None
        self._target_adapters: list[TargetAdaptor] = []

    def reset(self, rel_path: str) -> None:
        self._rel_path = rel_path
        self._target_adapters.clear()

    def add(self, target_adapter: TargetAdaptor) -> None:
        self._target_adapters.append(target_adapter)

    def rel_path(self) -> str:
        if self._rel_path is None:
            raise AssertionError(
                "The BUILD file rel_path was accessed before being set. This indicates a "
                "programming error in Pants. Please file a bug report at "
                "https://github.com/pantsbuild/pants/issues/new."
            )
        return self._rel_path

    def parsed_targets(self) -> list[TargetAdaptor]:
        return list(self._target_adapters)


class Parser:
    def __init__(
        self,
        *,
        build_root: str,
        target_type_aliases: Iterable[str],
        object_aliases: BuildFileAliases,
    ) -> None:
        self._symbols, self._parse_state = self._generate_symbols(
            build_root, target_type_aliases, object_aliases
        )

    @staticmethod
    def _generate_symbols(
        build_root: str,
        target_type_aliases: Iterable[str],
        object_aliases: BuildFileAliases,
    ) -> tuple[dict[str, Any], ParseState]:
        # N.B.: We re-use the thread local ParseState across symbols for performance reasons.
        # This allows a single construction of all symbols here that can be re-used for each BUILD
        # file parse with a reset of the ParseState for the calling thread.
        parse_state = ParseState()

        class Registrar:
            def __init__(self, type_alias: str) -> None:
                self._type_alias = type_alias

            def __call__(self, **kwargs: Any) -> TargetAdaptor:
                # Target names default to the name of the directory their BUILD file is in
                # (as long as it's not the root directory).
                if "name" not in kwargs:
                    dirname = os.path.basename(parse_state.rel_path())
                    if not dirname:
                        raise UnaddressableObjectError(
                            "Targets in root-level BUILD files must be named explicitly."
                        )
                    kwargs["name"] = dirname
                target_adaptor = TargetAdaptor(self._type_alias, **kwargs)
                parse_state.add(target_adaptor)
                return target_adaptor

        symbols: dict[str, Any] = dict(object_aliases.objects)
        symbols.update((alias, Registrar(alias)) for alias in target_type_aliases)

        parse_context = ParseContext(
            build_root=build_root, type_aliases=symbols, rel_path_oracle=parse_state
        )
        for alias, object_factory in object_aliases.context_aware_object_factories.items():
            symbols[alias] = object_factory(parse_context)

        return symbols, parse_state

    def parse(
        self, filepath: str, build_file_content: str, extra_symbols: BuildFilePreludeSymbols
    ) -> list[TargetAdaptor]:
        # TODO(#12915): We only combine these two mechanisms for performance, to avoid iterating
        #  over the file twice. Once we remove the CAOF rewrite mechanism, go back to using
        #  `tokenize` for erroring on imports.
        build_file_content = error_on_imports_and_rewrite_caofs_to_avoid_ambiguous_symbols(
            build_file_content, filepath, rename_symbols=False
        )

        self._parse_state.reset(rel_path=os.path.dirname(filepath))

        # We update the known symbols with Build File Preludes. This is subtle code; functions have
        # their own globals set on __globals__ which they derive from the environment where they
        # were executed. So for each extra_symbol which comes from a separate execution
        # environment, we need to to add all of our self._symbols to those __globals__, otherwise
        # those extra symbols will not see our target aliases etc. This also means that if multiple
        # prelude files are present, they probably cannot see each others' symbols. We may choose
        # to change this at some point.

        global_symbols = dict(self._symbols)
        for k, v in extra_symbols.symbols.items():
            if hasattr(v, "__globals__"):
                v.__globals__.update(global_symbols)
            global_symbols[k] = v

        try:
            exec(build_file_content, global_symbols)
        except NameError as e:
            valid_symbols = sorted(s for s in global_symbols.keys() if s != "__builtins__")
            original = e.args[0].capitalize()
            help_str = (
                "If you expect to see more symbols activated in the below list,"
                f" refer to {doc_url('enabling-backends')} for all available"
                " backends to activate."
            )

            candidates = get_close_matches(build_file_content, valid_symbols)
            if candidates:
                if len(candidates) == 1:
                    formatted_candidates = candidates[0]
                elif len(candidates) == 2:
                    formatted_candidates = " or ".join(candidates)
                else:
                    formatted_candidates = f"{', '.join(candidates[:-1])}, or {candidates[-1]}"
                help_str = f"Did you mean {formatted_candidates}?\n\n" + help_str
            raise ParseError(
                f"{original}.\n\n{help_str}\n\nAll registered symbols: {valid_symbols}"
            )

        return self._parse_state.parsed_targets()


def error_on_imports_and_rewrite_caofs_to_avoid_ambiguous_symbols(
    content: str, filepath: str, *, rename_symbols: bool
) -> str:
    """Error if imports are detected, which break sandboxing, and rewrite the symbol of context-
    aware object factories to avoid ambiguity with target generators.

    We use a simple heuristic of checking if `name` is set. If not, we assume it's a macro.
    """
    tree = ast.parse(content, filename=filepath)
    visitor = AstVisitor(filepath, rename_symbols=rename_symbols)
    visitor.visit(tree)
    if not visitor.pending_renames:
        return content
    lines = content.splitlines(keepends=True)
    for rename in visitor.pending_renames:
        idx = rename.lineno - 1
        lines[idx] = lines[idx].replace(f"{rename.old_symbol}(", f"{rename.new_symbol}(")
    return "".join(lines)


DEPRECATED_MACRO_RENAMES = {
    "python_requirements": "python_requirements_deprecated_macro",
    "poetry_requirements": "poetry_requirements_deprecated_macro",
    "pipenv_requirements": "pipenv_requirements_deprecated_macro",
    "pants_requirement": "pants_requirement_deprecated_macro",
}


class SymbolRename(NamedTuple):
    lineno: int
    old_symbol: str
    new_symbol: str


class AstVisitor(ast.NodeVisitor):
    def __init__(self, filepath: str, rename_symbols: bool) -> None:
        super().__init__()
        self.filepath = filepath
        self.rename_symbols = rename_symbols
        self.pending_renames: list[SymbolRename] = []

    def error_on_import(self, node: ast.Import | ast.ImportFrom) -> None:
        raise ParseError(
            f"Import used in {self.filepath} at line {node.lineno}. Import statements are "
            "banned in BUILD files because they can easily break Pants caching and lead to stale "
            "results.\n\n"
            f"Instead, consider writing a macro ({doc_url('macros')}) or writing a "
            f"plugin ({doc_url('plugins-overview')}."
        )

    def visit_Import(self, node: ast.Import) -> None:
        self.error_on_import(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.error_on_import(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            not self.rename_symbols
            or not isinstance(node.func, ast.Name)
            or node.func.id not in DEPRECATED_MACRO_RENAMES
        ):
            return
        name_keyword = next((kw for kw in node.keywords if kw.arg == "name"), None)
        if name_keyword is not None:
            return
        self.pending_renames.append(
            SymbolRename(
                node.lineno,
                old_symbol=node.func.id,
                new_symbol=DEPRECATED_MACRO_RENAMES[node.func.id],
            )
        )
