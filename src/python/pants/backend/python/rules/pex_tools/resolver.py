# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from argparse import ArgumentParser, Namespace
from pathlib import PurePath
from typing import List, NoReturn, Optional

from pex.interpreter import PythonInterpreter
from pex.resolver import LocalDistribution, Unsatisfiable, download

from pants.backend.python.rules.pex_tools.common import (
    DistributionDependencies,
    InterpreterNotFoundError,
    ParseBool,
    cli_environment,
    die,
)


def add_args(parser: ArgumentParser) -> None:
    parser.add_argument("requirements", nargs="*", metavar="REQUIREMENTS")
    parser.add_argument(
        "-r", "--requirement", "--requirement-file", dest="requirement_files", action="append"
    )
    parser.add_argument(
        "--constraints", "--constraint-file", dest="constraint_files", action="append"
    )
    ParseBool.add_argument(
        parser, "--pre", "--no-pre", "--prereleases", dest="prereleases", default=False,
    )
    ParseBool.custom_negative_prefixes("--intransitive").add_argument(
        parser, "--transitive", "--no-transitive", "--intransitive", default=True,
    )
    parser.add_argument("--platform", dest="platforms", action="append")
    ParseBool.add_argument(parser, "--build", "--no-build", default=True)
    ParseBool.add_argument(
        parser, "--wheel", "--no-wheel", "--no-use-wheel", dest="use_wheel", default=True,
    )
    parser.add_argument("--manylinux", default="manylinux2014")
    parser.add_argument("--dest")
    parser.add_argument("--single-interpreter", action="store_true", default=False)


def resolve(
    args: Namespace,
    jobs: int,
    cache: PurePath,
    indexes: Optional[List[str]],
    find_links: Optional[List[str]],
    interpreters: List[PythonInterpreter],
) -> DistributionDependencies:
    local_distributions: List[LocalDistribution] = download(
        requirements=args.requirements,
        requirement_files=args.requirement_files,
        constraint_files=args.constraint_files,
        allow_prereleases=args.prereleases,
        transitive=args.transitive,
        interpreters=interpreters,
        platforms=args.platforms,
        indexes=indexes,
        find_links=find_links,
        cache=str(cache),
        build=args.build,
        use_wheel=args.use_wheel,
        manylinux=args.manylinux,
        dest=args.dest,
        max_parallel_jobs=jobs,
    )
    return DistributionDependencies(dependencies=tuple(local_distributions))


def main() -> NoReturn:
    with cli_environment(
        description="Resolve requirements as individual installed wheel sys.path entries.",
        add_args=add_args,
    ) as env:
        try:
            interpreters = env.interpreter_factory.find_interpreters(env.args.single_interpreter)
        except InterpreterNotFoundError as e:
            die(f"Unable to find compatible interpreters: {e}")

        try:
            distribution_dependencies = resolve(
                args=env.args,
                jobs=env.jobs,
                cache=env.cache,
                indexes=env.indexes,
                find_links=env.find_links,
                interpreters=interpreters,
            )
        except Unsatisfiable as e:
            die(f"Unable to satisfy requirements: {e}")

        distribution_dependencies.dump(sys.stdout)
        sys.exit(0)
