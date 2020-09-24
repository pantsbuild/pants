# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent
from typing import Tuple

from pants.backend.python.target_types import (
    PythonInterpreterCompatibility,
    PythonRequirementsField,
    PythonSources,
)
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
from pants.engine.addresses import Address, Addresses, AddressInput
from pants.engine.fs import (
    CreateDigest,
    Digest,
    FileContent,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, TransitiveTargets
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class MyPyFieldSet(FieldSet):
    required_fields = (PythonSources,)

    sources: PythonSources


class MyPyRequest(TypecheckRequest):
    field_set_type = MyPyFieldSet


def generate_args(mypy: MyPy, *, file_list_path: str) -> Tuple[str, ...]:
    args = []
    if mypy.config:
        args.append(f"--config-file={mypy.config}")
    args.extend(mypy.args)
    args.append(f"@{file_list_path}")
    return tuple(args)


# MyPy searches for types for a package in packages containing a `py.types` marker file or else in
# a sibling `<package>-stubs` package as per PEP-0561. Going further than that PEP, MyPy restricts
# its search to `site-packages`. Since PEX deliberately isolates itself from `site-packages` as
# part of its raison d'être, we monkey-patch `site.getsitepackages` to look inside the scrubbed
# PEX sys.path before handing off to `mypy`. This will find dependencies installed via `mypy.pex`,
# along with the wheels we've extracted from `requirements.pex` and prefixed with the `.deps/`
# folder. Note that these extracted wheels
#
# As a complication, MyPy does its own validation to ensure packages aren't both available in
# site-packages and on the PYTHONPATH. As such, we elide all PYTHONPATH entries from artificial
# site-packages we set up since MyPy will manually scan PYTHONPATH outside this PEX to find
# packages. We also elide the values of PEX_EXTRA_SYS_PATH, which will be relative paths unlike
# every other entry of sys.path. (We can't directly look for PEX_EXTRA_SYS_PATH because Pex scrubs
# it.)
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

        PYTHONPATH = frozenset(
            os.path.realpath(p)
            for p in os.environ.get('PYTHONPATH', '').split(os.pathsep)
        )
        site.getsitepackages = lambda: [
            p for p in sys.path
            if p.startswith(".deps") or (
                os.path.realpath(p) not in PYTHONPATH and os.path.isabs(p)
            )
        ]
        site.getusersitepackages = lambda: ''  # i.e, the CWD.

        runpy.run_module('mypy', run_name='__main__')
        """
    ).encode(),
)


# TODO(#10131): Improve performance, e.g. by leveraging the MyPy cache.
# TODO(#10131): Support .pyi files.
@rule(desc="Typecheck using MyPy", level=LogLevel.DEBUG)
async def mypy_typecheck(
    request: MyPyRequest, mypy: MyPy, python_setup: PythonSetup
) -> TypecheckResults:
    if mypy.skip:
        return TypecheckResults([], typechecker_name="MyPy")

    plugin_target_addresses = await MultiGet(
        Get(Address, AddressInput, plugin_addr) for plugin_addr in mypy.source_plugins
    )

    plugin_transitive_targets_request = Get(TransitiveTargets, Addresses(plugin_target_addresses))
    typechecked_transitive_targets_request = Get(
        TransitiveTargets, Addresses(fs.address for fs in request.field_sets)
    )
    plugin_transitive_targets, typechecked_transitive_targets, launcher_script = await MultiGet(
        plugin_transitive_targets_request,
        typechecked_transitive_targets_request,
        Get(Digest, CreateDigest([LAUNCHER_FILE])),
    )

    plugin_requirements = PexRequirements.create_from_requirement_fields(
        plugin_tgt[PythonRequirementsField]
        for plugin_tgt in plugin_transitive_targets.closure
        if plugin_tgt.has_field(PythonRequirementsField)
    )

    # Interpreter constraints are tricky with MyPy:
    #  * MyPy requires running with Python 3.5+. If run with Python 3.5-3.7, MyPy can understand
    #     Python 2.7 and 3.4-3.7 thanks to the typed-ast library, but it can't understand 3.8+ If
    #     run with Python 3.8, it can understand 2.7 and 3.4-3.8. So, we need to check if the user
    #     has code that requires Python 3.8+, and if so, use a tighter requirement.
    #
    #     On top of this, MyPy parses the AST using the value from `python_version` from mypy.ini.
    #     If this is not configured, it defaults to the interpreter being used. This means that
    #     running MyPy with Py35 would choke on f-strings in Python 3.6, unless the user set
    #     `python_version`. We don't want to make the user set this up. (If they do, MyPy will use
    #     `python_version`, rather than defaulting to the executing interpreter).
    #
    #  * We must resolve third-party dependencies. This should use whatever the actual code's
    #     constraints are. However, PEX will error if they are not compatible
    #     with the interpreter being used to run MyPy. So, we should generally align the tool PEX
    #     constraints with the requirements constraints.
    #
    #     However, it's possible for the requirements' constraints to include Python 2 and not be
    #     compatible with MyPy's >=3.5 requirement. If any of the requirements only have
    #     Python 2 wheels and they are not compatible with Python 3, then Pex will error about
    #     missing wheels. So, in this case, we set `PEX_IGNORE_ERRORS`, which will avoid erroring,
    #     but may result in MyPy complaining that it cannot find certain distributions.
    code_interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
        (
            tgt[PythonInterpreterCompatibility]
            for tgt in typechecked_transitive_targets.closure
            if tgt.has_field(PythonInterpreterCompatibility)
        ),
        python_setup,
    )

    if not mypy.options.is_default("interpreter_constraints"):
        tool_interpreter_constraints = mypy.interpreter_constraints
    elif code_interpreter_constraints.requires_python38_or_newer():
        tool_interpreter_constraints = ("CPython>=3.8",)
    elif code_interpreter_constraints.requires_python37_or_newer():
        tool_interpreter_constraints = ("CPython>=3.7",)
    elif code_interpreter_constraints.requires_python36_or_newer():
        tool_interpreter_constraints = ("CPython>=3.6",)
    else:
        tool_interpreter_constraints = mypy.interpreter_constraints

    plugin_sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(plugin_transitive_targets.closure)
    )
    typechecked_sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(typechecked_transitive_targets.closure)
    )

    requirements_pex_request = Get(
        Pex,
        PexFromTargetsRequest,
        PexFromTargetsRequest.for_requirements(
            (field_set.address for field_set in request.field_sets),
            hardcoded_interpreter_constraints=code_interpreter_constraints,
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
            interpreter_constraints=PexInterpreterConstraints(tool_interpreter_constraints),
            entry_point=PurePath(LAUNCHER_FILE.path).stem,
        ),
    )

    config_digest_request = Get(
        Digest,
        PathGlobs(
            globs=[mypy.config] if mypy.config else [],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--mypy-config`",
        ),
    )

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
        f for f in typechecked_sources.source_files.snapshot.files if f.endswith(".py")
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
        "PEX_EXTRA_SYS_PATH": ":".join(
            itertools.chain(
                all_used_source_roots, extracted_pex_distributions.wheel_directory_paths
            )
        )
    }

    result = await Get(
        FallibleProcessResult,
        PexProcess(
            mypy_pex,
            argv=generate_args(mypy, file_list_path=file_list_path),
            input_digest=merged_input_files,
            extra_env=env,
            description=f"Run MyPy on {pluralize(len(typechecked_srcs_snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return TypecheckResults(
        [TypecheckResult.from_fallible_process_result(result)], typechecker_name="MyPy"
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(TypecheckRequest, MyPyRequest),
        *extract_pex.rules(),
        *pants_bin.rules(),
        *pex_from_targets.rules(),
    ]
