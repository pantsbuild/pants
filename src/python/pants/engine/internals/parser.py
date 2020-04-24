# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Type

from pants.engine.internals.struct import Struct
from pants.util.frozendict import FrozenDict


class ParseError(Exception):
    """Indicates an error parsing BUILD configuration."""


@dataclass(frozen=True)
class SymbolTable:
    """A symbol table dict mapping symbol name to implementation class."""

    table: Dict[str, Type]


# Needs to be in this file to avoid a circular dependency with build_files.
@dataclass(frozen=True)
class BuildFilePreludeSymbols:
    symbols: FrozenDict[str, Any]


@dataclass(frozen=True)
class HydratedStruct:
    """A wrapper around a Struct subclass post hydration.

    This exists so that the rule graph can statically provide a struct for a target, and rules can
    depend on this without needing to depend on having a concrete instance of SymbolTable to
    register their input selectors.
    """

    value: Struct


class Parser(ABC):
    @abstractmethod
    def parse(self, filepath: str, filecontent: bytes, extra_symbols: BuildFilePreludeSymbols):
        """
        :param filepath: The name of the file being parsed. The parser should not assume that the path
                         is accessible, and should consume the filecontent.
        :param filecontent: The raw byte content to parse.
        :param extra_symbols: Extra Python symbols to expose to the file when parsing it.
        :returns: A list of decoded addressable, Serializable objects. The callable will
                  raise :class:`ParseError` if there were any problems encountered parsing the filecontent.
        :rtype: :class:`collections.Callable`
        """
