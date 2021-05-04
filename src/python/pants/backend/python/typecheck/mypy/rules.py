# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from pants.backend.python.target_types import PythonRequirementsField, PythonSources
from pants.backend.python.typecheck.mypy.skip_field import SkipMyPyField
from pants.backend.python.typecheck.mypy.subsystem import MyPy
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
    VenvPex,
    VenvPexProcess,
)
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.typecheck import TypecheckRequest, TypecheckResult, TypecheckResults
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target, TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup
from pants.util.docutil import bracketed_docs_url
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MyPyFieldSet(FieldSet):
    required_fields = (PythonSources,)

    sources: PythonSources

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipMyPyField).value


@dataclass(frozen=True)
class MyPyPartition:
    root_targets: FrozenOrderedSet[Target]
    closure: FrozenOrderedSet[Target]
    interpreter_constraints: PexInterpreterConstraints
    python_version_already_configured: bool


class MyPyRequest(TypecheckRequest):
    field_set_type = MyPyFieldSet


def generate_argv(
    mypy: MyPy,
    typechecked_venv_pex: VenvPex,
    *,
    file_list_path: str,
    python_version: Optional[str],
) -> Tuple[str, ...]:
    args = [f"--python-executable={typechecked_venv_pex.python.argv0}", *mypy.args]
    if mypy.config:
        args.append(f"--config-file={mypy.config}")
    if python_version:
        args.append(f"--python-version={python_version}")
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
            f"({bracketed_docs_url('python-interpreter-compatibility')}). Instead, it will "
            "use what you set.\n\n(Automatically setting the option allows Pants to partition your "
            "targets by their constraints, so that, for example, you can run MyPy on Python 2-only "
            "code and Python 3-only code at the same time. This feature may no longer work.)"
        )
    return bool(configured)


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


@rule
async def mypy_typecheck_partition(partition: MyPyPartition, mypy: MyPy) -> TypecheckResult:
    plugin_target_addresses = await Get(Addresses, UnparsedAddressInputs, mypy.source_plugins)
    plugin_transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest(plugin_target_addresses)
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
    # and 3.7. However, typed-ast does not understand 3.8+, so instead we must run MyPy with
    # Python 3.8+ when relevant. We only do this if <3.8 can't be used, as we don't want a
    # loose requirement like `>=3.6` to result in requiring Python 3.8+, which would error if
    # 3.8+ is not installed on the machine.
    tool_interpreter_constraints = (
        partition.interpreter_constraints
        if (
            mypy.options.is_default("interpreter_constraints")
            and partition.interpreter_constraints.requires_python38_or_newer()
        )
        else PexInterpreterConstraints(mypy.interpreter_constraints)
    )

    plugin_sources_get = Get(
        PythonSourceFiles, PythonSourceFilesRequest(plugin_transitive_targets.closure)
    )
    closure_sources_get = Get(PythonSourceFiles, PythonSourceFilesRequest(partition.closure))
    roots_sources_get = Get(
        SourceFiles, SourceFilesRequest(tgt.get(PythonSources) for tgt in partition.root_targets)
    )

    requirements_pex_get = Get(
        Pex,
        PexFromTargetsRequest,
        PexFromTargetsRequest.for_requirements(
            (tgt.address for tgt in partition.root_targets),
            hardcoded_interpreter_constraints=partition.interpreter_constraints,
            internal_only=True,
        ),
    )

    # TODO(John Sirois): Scope the extra requirements to the partition.
    #  Right now we just use a global set of extra requirements and these might not be compatible
    #  with all partitions. See: https://github.com/pantsbuild/pants/issues/11556
    mypy_extra_requirements_pex_get = Get(
        Pex,
        PexRequest(
            output_filename="mypy_extra_requirements.pex",
            internal_only=True,
            requirements=PexRequirements(mypy.extra_requirements),
            interpreter_constraints=partition.interpreter_constraints,
        ),
    )
    mypy_pex_get = Get(
        VenvPex,
        PexRequest(
            output_filename="mypy.pex",
            internal_only=True,
            main=mypy.main,
            requirements=PexRequirements((*mypy.all_requirements, *plugin_requirements)),
            interpreter_constraints=tool_interpreter_constraints,
        ),
    )

    config_files_get = Get(ConfigFiles, ConfigFilesRequest, mypy.config_request)

    (
        plugin_sources,
        closure_sources,
        roots_sources,
        mypy_pex,
        requirements_pex,
        mypy_extra_requirements_pex,
        config_files,
    ) = await MultiGet(
        plugin_sources_get,
        closure_sources_get,
        roots_sources_get,
        mypy_pex_get,
        requirements_pex_get,
        mypy_extra_requirements_pex_get,
        config_files_get,
    )

    python_files = determine_python_files(roots_sources.snapshot.files)
    file_list_path = "__files.txt"
    file_list_digest_request = Get(
        Digest,
        CreateDigest([FileContent(file_list_path, "\n".join(python_files).encode())]),
    )

    typechecked_venv_pex_request = Get(
        VenvPex,
        PexRequest(
            output_filename="typechecked_venv.pex",
            internal_only=True,
            pex_path=[requirements_pex, mypy_extra_requirements_pex],
            interpreter_constraints=partition.interpreter_constraints,
        ),
    )

    typechecked_venv_pex, file_list_digest = await MultiGet(
        typechecked_venv_pex_request, file_list_digest_request
    )

    merged_input_files = await Get(
        Digest,
        MergeDigests(
            [
                file_list_digest,
                plugin_sources.source_files.snapshot.digest,
                closure_sources.source_files.snapshot.digest,
                typechecked_venv_pex.digest,
                config_files.snapshot.digest,
            ]
        ),
    )

    all_used_source_roots = sorted(
        set(itertools.chain(plugin_sources.source_roots, closure_sources.source_roots))
    )
    env = {
        "PEX_EXTRA_SYS_PATH": ":".join(all_used_source_roots),
        "MYPYPATH": ":".join(all_used_source_roots),
    }

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            mypy_pex,
            argv=generate_argv(
                mypy,
                typechecked_venv_pex,
                file_list_path=file_list_path,
                python_version=python_version,
            ),
            input_digest=merged_input_files,
            extra_env=env,
            description=f"Run MyPy on {pluralize(len(python_files), 'file')}.",
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
    config_files = await Get(ConfigFiles, ConfigFilesRequest, mypy.config_request)
    config_content = await Get(DigestContents, Digest, config_files.snapshot.digest)
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
        combined_roots: OrderedSet[Target] = OrderedSet()
        combined_closure: OrderedSet[Target] = OrderedSet()
        for transitive_targets in all_transitive_targets:
            combined_roots.update(transitive_targets.roots)
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
        *pex_from_targets.rules(),
    ]
