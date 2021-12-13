# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
from enum import Enum
from typing import cast

from pants.backend.python.dependency_inference import import_parser, module_mapper
from pants.backend.python.dependency_inference.default_unowned_dependencies import (
    DEFAULT_UNOWNED_DEPENDENCIES,
)
from pants.backend.python.dependency_inference.import_parser import (
    ParsedPythonImports,
    ParsePythonImportsRequest,
)
from pants.backend.python.dependency_inference.module_mapper import PythonModule, PythonModuleOwners
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonSourceField, PythonTestSourceField
from pants.backend.python.util_rules import ancestor_files, pex
from pants.backend.python.util_rules.ancestor_files import AncestorFiles, AncestorFilesRequest
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.rules import Get, MultiGet, SubsystemRule, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InferDependenciesRequest,
    InferredDependencies,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import OwnersNotFoundBehavior
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url
from pants.util.strutil import bullet_list

logger = logging.getLogger(__name__)


class UnownedDependencyError(Exception):
    """The inferred dependency does not have any owner."""


class UnownedDependencyUsage(Enum):
    """What action to take when an inferred dependency is unowned."""

    RaiseError = "error"
    LogWarning = "warning"
    DoNothing = "ignore"


class PythonInferSubsystem(Subsystem):
    options_scope = "python-infer"
    help = "Options controlling which dependencies will be inferred for Python targets."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--imports",
            default=True,
            type=bool,
            help=(
                "Infer a target's imported dependencies by parsing import statements from sources."
            ),
        )
        register(
            "--string-imports",
            default=False,
            type=bool,
            help=(
                "Infer a target's dependencies based on strings that look like dynamic "
                "dependencies, such as Django settings files expressing dependencies as strings. "
                "To ignore any false positives, put `!{bad_address}` in the `dependencies` field "
                "of your target."
            ),
        )
        register(
            "--string-imports-min-dots",
            default=2,
            type=int,
            help=(
                "If --string-imports is True, treat valid-looking strings with at least this many "
                "dots in them as potential dynamic dependencies. E.g., `'foo.bar.Baz'` will be "
                "treated as a potential dependency if this option is set to 2 but not if set to 3."
            ),
        )
        register(
            "--inits",
            default=False,
            type=bool,
            help=(
                "Infer a target's dependencies on any `__init__.py` files in the packages "
                "it is located in (recursively upward in the directory structure).\n\nEven if this "
                "is disabled, Pants will still include any ancestor `__init__.py` files, only they "
                "will not be 'proper' dependencies, e.g. they will not show up in "
                "`./pants dependencies` and their own dependencies will not be used.\n\nIf you "
                "have empty `__init__.py` files, it's safe to leave this option off; otherwise, "
                "you should enable this option."
            ),
        )
        register(
            "--conftests",
            default=True,
            type=bool,
            help=(
                "Infer a test target's dependencies on any conftest.py files in the current "
                "directory and ancestor directories."
            ),
        )
        register(
            "--entry-points",
            default=True,
            type=bool,
            help=(
                "Infer dependencies on targets' entry points, e.g. `pex_binary`'s "
                "`entry_point` field, `python_awslambda`'s `handler` field and "
                "`python_distribution`'s `entry_points` field."
            ),
        )
        register(
            "--unowned-dependency-behavior",
            type=UnownedDependencyUsage,
            default=UnownedDependencyUsage.DoNothing,
            help=("How to handle inferred dependencies that don't have any owner."),
        )

    @property
    def imports(self) -> bool:
        return cast(bool, self.options.imports)

    @property
    def string_imports(self) -> bool:
        return cast(bool, self.options.string_imports)

    @property
    def string_imports_min_dots(self) -> int:
        return cast(int, self.options.string_imports_min_dots)

    @property
    def inits(self) -> bool:
        return cast(bool, self.options.inits)

    @property
    def conftests(self) -> bool:
        return cast(bool, self.options.conftests)

    @property
    def entry_points(self) -> bool:
        return cast(bool, self.options.entry_points)

    @property
    def unowned_dependency_behavior(self) -> UnownedDependencyUsage:
        return cast(UnownedDependencyUsage, self.options.unowned_dependency_behavior)


class InferPythonImportDependencies(InferDependenciesRequest):
    infer_from = PythonSourceField


@rule(desc="Inferring Python dependencies by analyzing imports")
async def infer_python_dependencies_via_imports(
    request: InferPythonImportDependencies,
    python_infer_subsystem: PythonInferSubsystem,
    python_setup: PythonSetup,
) -> InferredDependencies:
    if not python_infer_subsystem.imports:
        return InferredDependencies([])

    wrapped_tgt = await Get(WrappedTarget, Address, request.sources_field.address)
    explicitly_provided_deps, detected_imports = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(wrapped_tgt.target[Dependencies])),
        Get(
            ParsedPythonImports,
            ParsePythonImportsRequest(
                cast(PythonSourceField, request.sources_field),
                InterpreterConstraints.create_from_targets([wrapped_tgt.target], python_setup),
                string_imports=python_infer_subsystem.string_imports,
                string_imports_min_dots=python_infer_subsystem.string_imports_min_dots,
            ),
        ),
    )

    owners_per_import = await MultiGet(
        Get(PythonModuleOwners, PythonModule(imported_module))
        for imported_module in detected_imports
    )

    merged_result: set[Address] = set()
    unowned_imports: set[str] = set()
    address = wrapped_tgt.target.address
    for owners, imp in zip(owners_per_import, detected_imports):
        merged_result.update(owners.unambiguous)
        explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
            owners.ambiguous,
            address,
            import_reference="module",
            context=f"The target {address} imports `{imp}`",
        )
        maybe_disambiguated = explicitly_provided_deps.disambiguated(owners.ambiguous)
        if maybe_disambiguated:
            merged_result.add(maybe_disambiguated)

        if not owners.unambiguous and imp.split(".")[0] not in DEFAULT_UNOWNED_DEPENDENCIES:
            unowned_imports.add(imp)

    unowned_dependency_behavior = python_infer_subsystem.unowned_dependency_behavior
    if unowned_imports and unowned_dependency_behavior is not UnownedDependencyUsage.DoNothing:
        raise_error = unowned_dependency_behavior is UnownedDependencyUsage.RaiseError
        log = logger.error if raise_error else logger.warning
        log(
            f"The following imports in {address} have no owners:\n\n{bullet_list(unowned_imports)}\n\n"
            "If you are expecting this import to be provided by your own firstparty code, ensure that it is contained within a source root. "
            "Otherwise if you are using a requirements file, consider adding the relevant package.\n"
            "Otherwise consider declaring a `python_requirement_library` target, which can then be inferred.\n"
            f"See {doc_url('python-third-party-dependencies')}"
        )

        if raise_error:
            raise UnownedDependencyError(
                "One or more unowned dependencies detected. Check logs for more details."
            )

    return InferredDependencies(sorted(merged_result))


class InferInitDependencies(InferDependenciesRequest):
    infer_from = PythonSourceField


@rule(desc="Inferring dependencies on `__init__.py` files")
async def infer_python_init_dependencies(
    request: InferInitDependencies, python_infer_subsystem: PythonInferSubsystem
) -> InferredDependencies:
    if not python_infer_subsystem.inits:
        return InferredDependencies([])

    fp = request.sources_field.file_path
    assert fp is not None
    init_files = await Get(
        AncestorFiles,
        AncestorFilesRequest(input_files=(fp,), requested=("__init__.py", "__init__.pyi")),
    )
    owners = await MultiGet(Get(Owners, OwnersRequest((f,))) for f in init_files.snapshot.files)
    return InferredDependencies(itertools.chain.from_iterable(owners))


class InferConftestDependencies(InferDependenciesRequest):
    infer_from = PythonTestSourceField


@rule(desc="Inferring dependencies on `conftest.py` files")
async def infer_python_conftest_dependencies(
    request: InferConftestDependencies,
    python_infer_subsystem: PythonInferSubsystem,
) -> InferredDependencies:
    if not python_infer_subsystem.conftests:
        return InferredDependencies([])

    fp = request.sources_field.file_path
    assert fp is not None
    conftest_files = await Get(
        AncestorFiles,
        AncestorFilesRequest(input_files=(fp,), requested=("conftest.py",)),
    )
    owners = await MultiGet(
        # NB: Because conftest.py files effectively always have content, we require an
        # owning target.
        Get(Owners, OwnersRequest((f,), OwnersNotFoundBehavior.error))
        for f in conftest_files.snapshot.files
    )
    return InferredDependencies(itertools.chain.from_iterable(owners))


# This is a separate function to facilitate tests registering import inference.
def import_rules():
    return [
        infer_python_dependencies_via_imports,
        *pex.rules(),
        *import_parser.rules(),
        *module_mapper.rules(),
        *stripped_source_files.rules(),
        SubsystemRule(PythonInferSubsystem),
        SubsystemRule(PythonSetup),
        UnionRule(InferDependenciesRequest, InferPythonImportDependencies),
    ]


def rules():
    return [
        *import_rules(),
        infer_python_init_dependencies,
        infer_python_conftest_dependencies,
        *ancestor_files.rules(),
        UnionRule(InferDependenciesRequest, InferInitDependencies),
        UnionRule(InferDependenciesRequest, InferConftestDependencies),
    ]
