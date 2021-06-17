# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import tokenize
from dataclasses import dataclass
from difflib import get_close_matches
from io import StringIO
from typing import Any, Dict, Iterable, List, Tuple, cast

from pants.base.exceptions import MappingError
from pants.base.parse_context import ParseContext
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.util.docutil import bracketed_docs_url
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class BuildFilePreludeSymbols:
    symbols: FrozenDict[str, Any]


class ParseError(Exception):
    """Indicates an error parsing BUILD configuration."""


class UnaddressableObjectError(MappingError):
    """Indicates an un-addressable object was found at the top level."""


class Parser:
    def __init__(
        self, *, target_type_aliases: Iterable[str], object_aliases: BuildFileAliases
    ) -> None:
        self._symbols, self._parse_context = self._generate_symbols(
            target_type_aliases, object_aliases
        )

    @staticmethod
    def _generate_symbols(
        target_type_aliases: Iterable[str],
        object_aliases: BuildFileAliases,
    ) -> Tuple[Dict[str, Any], ParseContext]:
        symbols: Dict[str, Any] = {}

        # Compute "per path" symbols.  For performance, we use the same ParseContext, which we
        # mutate to set the rel_path appropriately before it's actually used. This allows this
        # method to reuse the same symbols for all parses. Meanwhile, we set the rel_path to None,
        # so that we get a loud error if anything tries to use it before it's set.
        # TODO: See https://github.com/pantsbuild/pants/issues/3561
        parse_context = ParseContext(rel_path=None, type_aliases=symbols)

        class Registrar:
            def __init__(self, parse_context: ParseContext, type_alias: str):
                self._parse_context = parse_context
                self._type_alias = type_alias

            def __call__(self, *args, **kwargs):
                # Target names default to the name of the directory their BUILD file is in
                # (as long as it's not the root directory).
                if "name" not in kwargs:
                    dirname = os.path.basename(self._parse_context.rel_path)
                    if not dirname:
                        raise UnaddressableObjectError(
                            "Targets in root-level BUILD files must be named explicitly."
                        )
                    kwargs["name"] = dirname
                kwargs.setdefault("type_alias", self._type_alias)
                target_adaptor = TargetAdaptor(**kwargs)
                self._parse_context._storage.add(target_adaptor)
                return target_adaptor

        symbols.update({alias: Registrar(parse_context, alias) for alias in target_type_aliases})
        symbols.update(object_aliases.objects)
        for alias, object_factory in object_aliases.context_aware_object_factories.items():
            symbols[alias] = object_factory(parse_context)

        return symbols, parse_context

    def parse(
        self, filepath: str, build_file_content: str, extra_symbols: BuildFilePreludeSymbols
    ) -> List[TargetAdaptor]:
        # Mutate the parse context with the new path.
        self._parse_context._storage.clear(os.path.dirname(filepath))

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
                f" refer to {bracketed_docs_url('enabling-backends')} for all available"
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

        error_on_imports(build_file_content, filepath)

        return cast(List[TargetAdaptor], list(self._parse_context._storage.objects))


def error_on_imports(build_file_content: str, filepath: str) -> None:
    # This is poor sandboxing; there are many ways to get around this. But it's sufficient to tell
    # users who aren't malicious that they're doing something wrong, and it has a low performance
    # overhead.
    if "import" not in build_file_content:
        return
    io_wrapped_python = StringIO(build_file_content)
    for token in tokenize.generate_tokens(io_wrapped_python.readline):
        token_str = token[1]
        lineno, _ = token[2]
        if token_str != "import":
            continue
        raise ParseError(
            f"Import used in {filepath} at line {lineno}. Import statements are banned in "
            "BUILD files because they can easily break Pants caching and lead to stale results. "
            f"\n\nInstead, consider writing a macro ({bracketed_docs_url('macros')}) or "
            f"writing a plugin ({bracketed_docs_url('plugins-overview')}."
        )
