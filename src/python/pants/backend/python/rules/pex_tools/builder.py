# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
import tempfile
from argparse import ArgumentParser, Namespace
from contextlib import closing
from pathlib import PurePath
from typing import Callable, List, NoReturn, Optional
from uuid import uuid4

from pex.interpreter import PythonInterpreter
from pex.pex_builder import PEXBuilder
from pex.resolver import install

from pants.backend.python.rules.pex_tools.common import (
    DistributionDependencies,
    InterpreterNotFoundError,
    ParseBool,
    cli_environment,
    die,
)


def add_args(parser: ArgumentParser) -> None:
    parser.add_argument("-o", "--path", "--output-file")
    ParseBool.custom_negative_prefixes("--unzipped", "--not-zipped").add_argument(
        parser, "--zipped", "--unzipped", "--not-zipped", default=True
    )
    parser.add_argument("--preamble")
    ParseBool.custom_negative_prefixes("--link").add_argument(
        parser, "--copy", "--no-copy", "--link", default=True
    )
    ParseBool.add_argument(parser, "--strip-pex-env", "--no-strip-pex-env", default=False)
    parser.add_argument("--unzip", action="store_true", default=False)
    parser.add_argument("--inherit-path", default="false", choices=["false", "fallback", "prefer"])
    ParseBool.add_argument(parser, "--zip-safe", "--not-zip-safe", default=True)
    parser.add_argument("--ignore-errors", action="store_true", default=False)
    parser.add_argument("--always-write-cache", action="store_true", default=False)
    parser.add_argument("--pex-path")
    parser.add_argument("--python-shebang", dest="shebang")
    parser.add_argument("-m", "-e", "--entry-point")
    parser.add_argument("-c", "--script", "--console-script")
    parser.add_argument("-D", "--sources-directory", dest="source_directories", action="append")
    parser.add_argument("-R", "--resources-directory", dest="resource_directories", action="append")
    parser.add_argument("--dependency-manifest")
    ParseBool.add_argument(parser, "--compile", "--no-compile", default=False)
    ParseBool.add_argument(parser, "--use-system-time", "--no-use-system-time", default=False)


def walk_and_do(fn: Callable[[str, str], None], src_dir: str) -> None:
    src_dir = os.path.realpath(src_dir)
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            src_file_path = os.path.join(root, f)
            dst_path = os.path.relpath(src_file_path, src_dir)
            fn(src_file_path, dst_path)


def load_dependencies(dependency_manifest: str) -> DistributionDependencies:
    with closing(sys.stdin if dependency_manifest == "-" else open(dependency_manifest)) as fp:
        return DistributionDependencies.load(fp)


def build(
    args: Namespace,
    jobs: int,
    cache: PurePath,
    indexes: Optional[List[str]],
    find_links: Optional[List[str]],
    interpreter_constraints: Optional[List[str]],
    interpreter: PythonInterpreter,
) -> str:
    if args.entry_point and args.script:
        die("Must specify at most one entry point or script.")

    pex_path: str = args.path if args.path else tempfile.mkdtemp(
        dir=os.path.realpath(os.curdir), suffix=".pex"
    )

    builder = PEXBuilder(
        path=f"{pex_path}.{uuid4().hex}" if args.zipped else pex_path,
        interpreter=interpreter,
        preamble=args.preamble,
        copy=args.copy,
    )

    builder.info.strip_pex_env = args.strip_pex_env
    builder.info.pex_root = str(cache)
    builder.info.unzip = args.unzip
    builder.info.inherit_path = args.inherit_path
    builder.info.zip_safe = args.zip_safe
    builder.info.ignore_errors = args.ignore_errors
    builder.info.always_write_cache = args.always_write_cache
    builder.info.merge_pex_path(args.pex_path)
    builder.info.emit_warnings = args.emit_warnings

    if args.shebang:
        builder.set_shebang(args.shebang)

    if interpreter_constraints:
        for interpreter_constraint in interpreter_constraints:
            builder.add_interpreter_constraint(interpreter_constraint)

    if args.source_directories:
        for source_directory in args.source_directories:
            walk_and_do(builder.add_source, source_directory)

    if args.resource_directories:
        for resource_directory in args.resource_directories:
            walk_and_do(builder.add_resource, resource_directory)

    if args.dependency_manifest:
        dependency_manifest: str = args.dependency_manifest
        distribution_dependencies = load_dependencies(dependency_manifest)
        for installed_distribution in install(
            list(distribution_dependencies.dependencies),
            indexes=indexes,
            find_links=find_links,
            cache=str(cache),
            compile=args.compile,
            max_parallel_jobs=jobs,
            ignore_errors=args.ignore_errors,
        ):
            builder.add_distribution(installed_distribution.distribution)
            builder.add_requirement(installed_distribution.requirement)

    if args.entry_point:
        builder.set_entry_point(args.entry_point)
    elif args.script:
        builder.set_script(args.script)

    if args.zipped:
        builder.build(
            filename=args.path,
            bytecode_compile=args.compile,
            deterministic_timestamp=not args.use_system_time,
        )
    else:
        builder.freeze(bytecode_compile=args.compile)

    return pex_path


def main() -> NoReturn:
    with cli_environment(
        description="Build a PEX from sources and a requirement manifest.", add_args=add_args
    ) as env:
        try:
            interpreter = env.interpreter_factory.find_interpreter()
        except InterpreterNotFoundError as e:
            die(f"Unable to find a compatible interpreter: {e}")

        try:
            pex_path = build(
                args=env.args,
                jobs=env.jobs,
                cache=env.cache,
                indexes=env.indexes,
                find_links=env.find_links,
                interpreter_constraints=env.interpreter_factory.constraints,
                interpreter=interpreter,
            )
        except PEXBuilder.ImmutablePEX as e:
            die(f"PEXBuilder was unexpectedly frozen: {e}")
        except PEXBuilder.InvalidDistribution as e:
            die(f"Failed to add distribution: {e}")
        except PEXBuilder.InvalidDependency as e:
            die(f"Failed to add dependency: {e}")
        except PEXBuilder.InvalidExecutableSpecification as e:
            die(f"Failed to set PEX entry point: {e}")
        except PEXBuilder.Error as e:
            die(f"Failed to build PEX: {e}")

        print(f"{pex_path}")
        sys.exit(0)
