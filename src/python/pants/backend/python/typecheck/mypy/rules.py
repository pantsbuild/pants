# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent
from typing import Iterable, Optional, Tuple

from pants.backend.python.target_types import PythonRequirementsField, PythonSources
from pants.backend.python.typecheck.mypy.subsystem import MyPy
from pants.backend.python.util_rules import extract_pex, pex_from_targets
from pants.backend.python.util_rules.extract_pex import ExtractedPexDistributions
from pants.backend.python.util_rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexProcess,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.typecheck import TypecheckRequest, TypecheckResult, TypecheckResults
from pants.core.util_rules import pants_bin
from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target, TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MyPyFieldSet(FieldSet):
    required_fields = (PythonSources,)

    sources: PythonSources


@dataclass(frozen=True)
class MyPyPartition:
    field_set_addresses: FrozenOrderedSet[Address]
    closure: FrozenOrderedSet[Target]
    interpreter_constraints: PexInterpreterConstraints
    python_version_already_configured: bool


class MyPyRequest(TypecheckRequest):
    field_set_type = MyPyFieldSet


def generate_argv(
    mypy: MyPy, *, file_list_path: str, python_version: Optional[str]
) -> Tuple[str, ...]:
    args = []
    if mypy.config:
        args.append(f"--config-file={mypy.config}")
    if python_version:
        args.append(f"--python-version={python_version}")
    args.extend(mypy.args)
    args.append(f"@{file_list_path}")
    return tuple(args)


def check_and_warn_if_python_version_configured(
    *, config: Optional[FileContent], args: Tuple[str, ...]
) -> bool:
    configured = []
    if config and b"python_version" in config.content:
        configured.append(
            f"`python_version` in {config.path} (which is used because of the "
            "`[mypy].config` option)"
        )
    if "--py2" in args:
        configured.append("`--py2` in the `--mypy-args` option")
    if any(arg.startswith("--python-version") for arg in args):
        configured.append("`--python-version` in the `--mypy-args` option")
    if configured:
        formatted_configured = " and you set ".join(configured)
        logger.warning(
            f"You set {formatted_configured}. Normally, Pants would automatically set this for you "
            "based on your code's interpreter constraints "
            "(https://www.pantsbuild.org/docs/python-interpreter-compatibility). Instead, it will "
            "use what you set.\n\n(Automatically setting the option allows Pants to partition your "
            "targets by their constraints, so that, for example, you can run MyPy on Python 2-only "
            "code and Python 3-only code at the same time. This feature may no longer work.)"
        )
    return bool(configured)


def config_path_globs(mypy: MyPy) -> PathGlobs:
    return PathGlobs(
        globs=[mypy.config] if mypy.config else [],
        glob_match_error_behavior=GlobMatchErrorBehavior.error,
        description_of_origin="the option `--mypy-config`",
    )


def determine_python_files(files: Iterable[str]) -> Tuple[str, ...]:
    """We run over all .py and .pyi files, but .pyi files take precedence.

    MyPy will error if we say to run over the same module with both its .py and .pyi files, so we
    must be careful to only use the .pyi stub.
    """
    result: OrderedSet[str] = OrderedSet()
    for f in files:
        if f.endswith(".pyi"):
            py_file = f[:-1]  # That is, strip the `.pyi` suffix to be `.py`.
            result.discard(py_file)
            result.add(f)
        elif f.endswith(".py"):
            pyi_file = f + "i"
            if pyi_file not in result:
                result.add(f)
    return tuple(result)


# MyPy searches for types for a package in packages containing a `py.types` marker file or else in
# a sibling `<package>-stubs` package as per PEP-0561. Going further than that PEP, MyPy restricts
# its search to `site-packages`. Since PEX deliberately isolates itself from `site-packages` as
# part of its raison d'être, we monkey-patch `site.getsitepackages` to look inside the scrubbed
# PEX sys.path before handing off to `mypy`. This will find dependencies installed in the
# `mypy.pex`, such as MyPy itself and any third-party plugins installed via
# `--mypy-extra-requirements`.
#
# We also include the values from our custom env var `EXTRACTED_WHEELS` in this monkey-patch. For
# user's third-party requirements, we don't include them in the `mypy.pex`, as the interpreter
# constraints for their own code may be different than what's used to run MyPy, and this would
# cause issues with Pex. Instead, we extract out the `.deps` folder from `requirements.pex`, and
# set the env var `EXTRACTED_WHEELS` to point to each entry. This allows MyPy to know about user's
# third-party requirements without having to set them on PYTHONPATH.
#
# Finally, we elide the values of PEX_EXTRA_SYS_PATH, which will point to user's first-party code's
# source roots. MyPy validates that the same paths are not available both in site-packages and
# PYTHONPATH, so we must not add this first-party code to site-packages. We use a heuristic of
# looking for relative paths, as all other entries will be absolute paths. (We can't directly look
# for PEX_EXTRA_SYS_PATH because Pex scrubs it.)
#
# See:
#   https://mypy.readthedocs.io/en/stable/installed_packages.html#installed-packages
#   https://www.python.org/dev/peps/pep-0561/#stub-only-packages
#   https://github.com/python/mypy/blob/f743b0af0f62ce4cf8612829e50310eb0a019724/mypy/sitepkgs.py#L22-L28
LAUNCHER_FILE = FileContent(
    "__pants_mypy_launcher.py",
    dedent(
        """\
        import os
        import runpy
        import site
        import sys

        site.getsitepackages = lambda: [
            *(p for p in sys.path if os.path.isabs(p)),
            *os.environ.get('EXTRACTED_WHEELS').split(os.pathsep),
        ]
        site.getusersitepackages = lambda: ''  # i.e, the CWD.

        runpy.run_module('mypy', run_name='__main__')
        """
    ).encode(),
)


@rule
async def mypy_typecheck_partition(partition: MyPyPartition, mypy: MyPy) -> TypecheckResult:
    plugin_target_addresses = await Get(Addresses, UnparsedAddressInputs, mypy.source_plugins)
    plugin_transitive_targets_request = Get(
        TransitiveTargets, TransitiveTargetsRequest(plugin_target_addresses)
    )
    plugin_transitive_targets, launcher_script = await MultiGet(
        plugin_transitive_targets_request, Get(Digest, CreateDigest([LAUNCHER_FILE]))
    )

    plugin_requirements = PexRequirements.create_from_requirement_fields(
        plugin_tgt[PythonRequirementsField]
        for plugin_tgt in plugin_transitive_targets.closure
        if plugin_tgt.has_field(PythonRequirementsField)
    )

    # If the user did not set `--python-version` already, we set it ourselves based on their code's
    # interpreter constraints. This determines what AST is used by MyPy.
    python_version = (
        None
        if partition.python_version_already_configured
        else partition.interpreter_constraints.minimum_python_version()
    )

    # MyPy requires 3.5+ to run, but uses the typed-ast library to work with 2.7, 3.4, 3.5, 3.6,
    # and 3.7. However, typed-ast does not understand 3.8, so instead we must run MyPy with
    # Python 3.8 when relevant. We only do this if <3.8 can't be used, as we don't want a
    # loose requirement like `>=3.6` to result in requiring Python 3.8, which would error if
    # 3.8 is not installed on the machine.
    tool_interpreter_constraints = PexInterpreterConstraints(
        ("CPython>=3.8",)
        if (
            mypy.options.is_default("interpreter_constraints")
            and partition.interpreter_constraints.requires_python38_or_newer()
        )
        else mypy.interpreter_constraints
    )

    plugin_sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(plugin_transitive_targets.closure)
    )
    typechecked_sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(partition.closure)
    )

    # Normally, this `requirements.pex` would be merged with mypy.pex via `--pex-path`. However,
    # this will cause a runtime error if the interpreter constraints are different between the
    # PEXes and they have incompatible wheels.
    #
    # Instead, we teach MyPy about the requirements by extracting the distributions from
    # requirements.pex and setting EXTRACTED_WHEELS, which our custom launcher script then
    # looks for.
    #
    # Conventionally, MyPy users might instead set `MYPYPATH` for this. However, doing this
    # results in type checking the requirements themselves.
    requirements_pex_request = Get(
        Pex,
        PexFromTargetsRequest,
        PexFromTargetsRequest.for_requirements(
            (addr for addr in partition.field_set_addresses),
            hardcoded_interpreter_constraints=partition.interpreter_constraints,
            internal_only=True,
        ),
    )
    mypy_pex_request = Get(
        Pex,
        PexRequest(
            output_filename="mypy.pex",
            internal_only=True,
            sources=launcher_script,
            requirements=PexRequirements(
                itertools.chain(mypy.all_requirements, plugin_requirements)
            ),
            interpreter_constraints=tool_interpreter_constraints,
            entry_point=PurePath(LAUNCHER_FILE.path).stem,
        ),
    )

    config_digest_request = Get(Digest, PathGlobs, config_path_globs(mypy))

    (
        plugin_sources,
        typechecked_sources,
        mypy_pex,
        requirements_pex,
        config_digest,
    ) = await MultiGet(
        plugin_sources_request,
        typechecked_sources_request,
        mypy_pex_request,
        requirements_pex_request,
        config_digest_request,
    )

    typechecked_srcs_snapshot = typechecked_sources.source_files.snapshot
    file_list_path = "__files.txt"
    python_files = "\n".join(
        determine_python_files(typechecked_sources.source_files.snapshot.files)
    )
    create_file_list_request = Get(
        Digest,
        CreateDigest([FileContent(file_list_path, python_files.encode())]),
    )

    file_list_digest, extracted_pex_distributions = await MultiGet(
        create_file_list_request, Get(ExtractedPexDistributions, Pex, requirements_pex)
    )

    merged_input_files = await Get(
        Digest,
        MergeDigests(
            [
                file_list_digest,
                plugin_sources.source_files.snapshot.digest,
                typechecked_srcs_snapshot.digest,
                mypy_pex.digest,
                extracted_pex_distributions.digest,
                config_digest,
            ]
        ),
    )

    all_used_source_roots = sorted(
        set(itertools.chain(plugin_sources.source_roots, typechecked_sources.source_roots))
    )
    env = {
        "PEX_EXTRA_SYS_PATH": ":".join(all_used_source_roots),
        "EXTRACTED_WHEELS": ":".join(extracted_pex_distributions.wheel_directory_paths),
    }

    result = await Get(
        FallibleProcessResult,
        PexProcess(
            mypy_pex,
            argv=generate_argv(mypy, file_list_path=file_list_path, python_version=python_version),
            input_digest=merged_input_files,
            extra_env=env,
            description=f"Run MyPy on {pluralize(len(typechecked_srcs_snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return TypecheckResult.from_fallible_process_result(
        result, partition_description=str(sorted(str(c) for c in partition.interpreter_constraints))
    )


# TODO(#10864): Improve performance, e.g. by leveraging the MyPy cache.
@rule(desc="Typecheck using MyPy", level=LogLevel.DEBUG)
async def mypy_typecheck(
    request: MyPyRequest, mypy: MyPy, python_setup: PythonSetup
) -> TypecheckResults:
    if mypy.skip:
        return TypecheckResults([], typechecker_name="MyPy")

    # We batch targets by their interpreter constraints to ensure, for example, that all Python 2
    # targets run together and all Python 3 targets run together. We can only do this by setting
    # the `--python-version` option, but we allow the user to set it as a safety valve. We warn if
    # they've set the option.
    config_content = await Get(DigestContents, PathGlobs, config_path_globs(mypy))
    python_version_configured = check_and_warn_if_python_version_configured(
        config=next(iter(config_content), None), args=mypy.args
    )

    # When determining how to batch by interpreter constraints, we must consider the entire
    # transitive closure to get the final resulting constraints.
    # TODO(#10863): Improve the performance of this.
    transitive_targets_per_field_set = await MultiGet(
        Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address]))
        for field_set in request.field_sets
    )

    interpreter_constraints_to_transitive_targets = defaultdict(set)
    for transitive_targets in transitive_targets_per_field_set:
        interpreter_constraints = PexInterpreterConstraints.create_from_targets(
            transitive_targets.closure, python_setup
        ) or PexInterpreterConstraints(mypy.interpreter_constraints)
        interpreter_constraints_to_transitive_targets[interpreter_constraints].add(
            transitive_targets
        )

    partitions = []
    for interpreter_constraints, all_transitive_targets in sorted(
        interpreter_constraints_to_transitive_targets.items()
    ):
        combined_roots: OrderedSet[Address] = OrderedSet()
        combined_closure: OrderedSet[Target] = OrderedSet()
        for transitive_targets in all_transitive_targets:
            combined_roots.update(tgt.address for tgt in transitive_targets.roots)
            combined_closure.update(transitive_targets.closure)
        partitions.append(
            MyPyPartition(
                FrozenOrderedSet(combined_roots),
                FrozenOrderedSet(combined_closure),
                interpreter_constraints,
                python_version_already_configured=python_version_configured,
            )
        )

    partitioned_results = await MultiGet(
        Get(TypecheckResult, MyPyPartition, partition) for partition in partitions
    )
    return TypecheckResults(partitioned_results, typechecker_name="MyPy")


def rules():
    return [
        *collect_rules(),
        UnionRule(TypecheckRequest, MyPyRequest),
        *extract_pex.rules(),
        *pants_bin.rules(),
        *pex_from_targets.rules(),
    ]
