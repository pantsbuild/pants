# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import sys
from argparse import Action, ArgumentParser, ArgumentTypeError, Namespace
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePath
from typing import (
    Any,
    Callable,
    ClassVar,
    DefaultDict,
    Dict,
    Iterable,
    Iterator,
    List,
    NoReturn,
    Optional,
    Sequence,
    TextIO,
    Tuple,
    Type,
    Union,
)

from pex.common import safe_mkdtemp
from pex.distribution_target import DistributionTarget
from pex.interpreter import PythonIdentity, PythonInterpreter
from pex.jobs import DEFAULT_MAX_JOBS
from pex.platforms import Platform
from pex.resolver import LocalDistribution
from pex.variables import ENV


class ParseBool(Action):
    _TRUE_VALUES = ("1", "true", "yes")
    _FALSE_VALUES = ("0", "false", "no")

    _negative_prefixes: ClassVar[Tuple[str, ...]] = ("--no-",)

    @classmethod
    def custom_negative_prefixes(cls, *negative_prefixes: str) -> "Type[ParseBool]":
        class CustomizedParseBool(ParseBool):
            _negative_prefixes = cls._negative_prefixes + negative_prefixes

        return CustomizedParseBool

    @classmethod
    def _parse_bool(cls, value: str) -> bool:
        normalized_value = value.lower()
        if normalized_value in cls._TRUE_VALUES:
            return True
        if normalized_value in cls._FALSE_VALUES:
            return False
        raise ArgumentTypeError(
            f"Expected one of {', '.join(map(repr, cls._TRUE_VALUES + cls._FALSE_VALUES))} but "
            f"given {value!r}"
        )

    @classmethod
    def add_argument(
        cls, parser: ArgumentParser, *flags: str, default: bool, **kwargs: Any
    ) -> None:
        keyword_args = dict(action=cls, nargs="?", **kwargs, default=default)
        parser.add_argument(*flags, **keyword_args)

    def __call__(
        self,
        parser: ArgumentParser,
        namespace: Namespace,
        values: Optional[Union[str, Sequence[Any]]] = None,
        option_string: Optional[str] = None,
    ) -> None:
        assert isinstance(values, (type(None), str))
        assert option_string is not None

        value = self._parse_bool(values) if values is not None else True
        negative = option_string.startswith(self._negative_prefixes)
        setattr(namespace, self.dest, value ^ negative)


class InterpreterNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class InterpreterFactory:
    constraints: Optional[List[str]] = None
    search_path: Optional[List[str]] = None

    def find_interpreter(self) -> PythonInterpreter:
        return next(self._iter_interpreters(single=True))

    def find_interpreters(self, single: bool = False) -> List[PythonInterpreter]:
        return list(self._iter_interpreters(single=single))

    def _iter_interpreters(self, single: bool) -> Iterator[PythonInterpreter]:
        if not self.constraints:
            yield PythonInterpreter.get()
            return

        found = False
        for interpreter in PythonInterpreter.iter(paths=self.search_path):
            identity: PythonIdentity = interpreter.identity
            for interpreter_constraint in self.constraints:
                if identity.matches(interpreter_constraint):
                    yield interpreter
                    found = True
                    if single:
                        return
        if not found:
            constraints = " OR ".join(map(repr, self.constraints))
            search_path = (
                os.pathsep.join(self.search_path)
                if self.search_path
                else os.environ.get("PATH", "$PATH")
            )
            raise InterpreterNotFoundError(
                f"Failed to find any interpreters satisfying constraints {constraints} "
                f"after searching {search_path}"
            )


@dataclass(frozen=True)
class DistributionDependencies:
    dependencies: Iterable[LocalDistribution] = ()

    @classmethod
    def load(cls: "Type[DistributionDependencies]", fp: TextIO) -> "DistributionDependencies":
        manifest: List[Dict[str, Any]] = json.load(fp)

        dependencies: List[LocalDistribution] = []
        for local_distribution_info in manifest:
            target_info: Dict[str, str] = local_distribution_info["target"]
            if "platform" in target_info:
                target = DistributionTarget.for_platform(Platform.create(target_info["platform"]))
            else:
                target = DistributionTarget.for_interpreter(
                    PythonInterpreter.from_binary(target_info["interpreter"])
                )

            distributions: List[Dict[str, str]] = local_distribution_info["distributions"]
            dependencies.extend(
                LocalDistribution.create(
                    target=target, path=dist_info["path"], fingerprint=dist_info["fingerprint"]
                )
                for dist_info in distributions
            )
        return cls(dependencies=tuple(dependencies))

    def dump(self, fp: TextIO, **kwargs) -> None:
        distributions_by_target: DefaultDict[
            DistributionTarget, List[LocalDistribution]
        ] = defaultdict(list)
        for local_distribution in self.dependencies:
            distributions_by_target[local_distribution.target].append(local_distribution)

        manifest: List[Dict[str, Any]] = []
        for target, local_distributions in distributions_by_target.items():
            target_info: Dict[str, str] = {
                "platform"
                if target.is_foreign
                else "interpreter": str(target.get_platform())
                if target.is_foreign
                else target.get_interpreter().binary
            }
            manifest.append(
                {
                    "target": target_info,
                    "distributions": [
                        {
                            "path": local_distribution.path,
                            "fingerprint": local_distribution.fingerprint,
                        }
                        for local_distribution in local_distributions
                    ],
                }
            )

        json.dump(manifest, fp, **kwargs)


@dataclass(frozen=True)
class CliEnvironment:
    args: Namespace
    cache: PurePath
    interpreter_factory: InterpreterFactory
    indexes: Optional[List[str]]
    find_links: Optional[List[str]]
    jobs: int = DEFAULT_MAX_JOBS


def calculate_indexes(pypi: bool, indexes: Optional[List[str]] = None) -> List[str]:
    if not pypi:
        return indexes[:] if indexes else []

    PyPI = "https://pypi.org/simple"
    if indexes:
        if PyPI not in indexes:
            return [PyPI, *indexes]
        return indexes[:]
    return [PyPI]


@contextmanager
def cli_environment(
    description: str, add_args: Callable[[ArgumentParser], None]
) -> Iterator[CliEnvironment]:
    parser = ArgumentParser(description=description)
    parser.add_argument("-v", dest="verbosity", action="count", default=0)
    ParseBool.add_argument(
        parser, "--emit-warnings", "--no-emit-warnings", dest="emit_warnings", default=True
    )
    parser.add_argument("-i", "--index", dest="indexes", action="append")
    ParseBool.add_argument(parser, "--pypi", "--no-pypi", "--no-index", default=True)
    parser.add_argument("-f", "--find-links", "--repo", action="append")
    parser.add_argument("--cache")
    parser.add_argument("--interpreter-constraint", dest="interpreter_constraints", action="append")
    parser.add_argument(
        "--interpreter-search-path", dest="interpreter_search_paths", action="append"
    )
    parser.add_argument("-j", "--jobs", type=int, default=DEFAULT_MAX_JOBS)
    add_args(parser)

    args = parser.parse_args()

    cache = PurePath(args.cache or safe_mkdtemp())
    with ENV.patch(
        PEX_VERBOSE=args.verbosity, PEX_EMIT_WARNINGS=args.emit_warnings, PEX_ROOT=cache
    ):
        yield CliEnvironment(
            args=args,
            cache=cache,
            interpreter_factory=InterpreterFactory(
                constraints=args.interpreter_constraints, search_path=args.interpreter_search_paths
            ),
            indexes=calculate_indexes(args.pypi, args.indexes),
            find_links=args.find_links,
            jobs=args.jobs,
        )


def die(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    sys.exit(1)
