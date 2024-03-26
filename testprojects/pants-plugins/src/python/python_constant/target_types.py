# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import ast
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, DefaultDict, List, Set, Tuple, cast

from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyPythonModuleMapping,
    ResolveName,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField, PythonSourceField
from pants.engine.addresses import Addresses
from pants.engine.collection import Collection
from pants.engine.fs import Digest, DigestContents
from pants.engine.internals.target_adaptor import SourceBlock, SourceBlocks
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    Dependencies,
    FieldSet,
    GeneratedTargets,
    GenerateTargetsRequest,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    IntField,
    SingleSourceField,
    SourcesPaths,
    SourcesPathsRequest,
    StringField,
    Target,
    TargetGenerator,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


class PythonConstantSourceField(SingleSourceField):
    required = True


class PythonConstantDependencies(Dependencies):
    pass


class PythonConstantLinenoField(IntField):
    alias = "lineno"


class PythonConstantEndLinenoField(IntField):
    alias = "end_lineno"


class PythonConstantNameField(StringField):
    alias = "constant"


class PythonConstantTarget(Target):
    alias = "python_constant"
    core_fields = (
        PythonConstantSourceField,
        PythonConstantNameField,
        PythonConstantLinenoField,
        PythonConstantEndLinenoField,
        PythonConstantDependencies,
    )


class PythonConstantTargetGenerator(TargetGenerator):
    alias = "python_constants"
    generated_target_cls = PythonConstantTarget
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PythonConstantSourceField,
        PythonConstantDependencies,
    )
    copied_fields = (
        *COMMON_TARGET_FIELDS,
        PythonConstantSourceField,
    )
    moved_fields = (PythonConstantDependencies,)


class GeneratePythonConstantTargetsRequest(GenerateTargetsRequest):
    generate_from = PythonConstantTargetGenerator


@dataclass
class PythonConstant:
    python_contant: str
    lineno: int
    end_lineno: int


class PythonConstantVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        super().__init__()
        self._constants: list[PythonConstant] = []

    def visit_Module(self, node: ast.Module) -> Any:
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        assert stmt.end_lineno
                        self._constants.append(
                            PythonConstant(target.id, stmt.lineno, stmt.end_lineno)
                        )

    @classmethod
    def parse_constants(cls, content: bytes) -> list[PythonConstant]:
        parsed = ast.parse(content.decode("utf-8"))
        v = PythonConstantVisitor()
        v.visit(parsed)
        return v._constants


@rule
async def generate_python_contant_targets(
    request: GeneratePythonConstantTargetsRequest,
) -> GeneratedTargets:
    hydrated_sources = await Get(
        HydratedSources,
        HydrateSourcesRequest(request.generator[PythonConstantSourceField]),
    )
    logger.debug("python_contant sources: %s", hydrated_sources)
    digest_files = await Get(DigestContents, Digest, hydrated_sources.snapshot.digest)
    content = digest_files[0].content
    python_contants = PythonConstantVisitor.parse_constants(content)
    logger.debug("parsed python_contants: %s", python_contants)
    return GeneratedTargets(
        request.generator,
        [
            PythonConstantTarget(
                {
                    **request.template,
                    PythonConstantNameField.alias: python_contant.python_contant,
                },
                request.template_address.create_generated(python_contant.python_contant),
                origin_sources_blocks=FrozenDict(
                    {
                        digest_files[0].path: SourceBlocks(
                            [
                                SourceBlock(
                                    start=python_contant.lineno,
                                    end=python_contant.end_lineno + 1,
                                ),
                            ]
                        ),
                    }
                ),
            )
            for python_contant in python_contants
        ],
    )


@dataclass(frozen=True)
class InferPythonDependenciesOnPythonConstantsFieldSet(FieldSet):
    required_fields = (PythonSourceField, PythonResolveField)

    source: PythonSourceField
    resolve: PythonResolveField


class InferPythonDependenciesOnPythonConstantsRequest(
    InferDependenciesRequest[InferPythonDependenciesOnPythonConstantsFieldSet]
):
    infer_from = InferPythonDependenciesOnPythonConstantsFieldSet


@dataclass(frozen=True)
class Var:
    module: str
    name: str


class ImportVisitor(ast.NodeVisitor):
    def __init__(self, search_for_modules: set[str]) -> None:
        super().__init__()
        self._search_for = search_for_modules
        self._found: Set[Var] = set()

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        if node.module not in self._search_for:
            return

        for alias in node.names:
            self._found.add(Var(node.module, alias.name))

    @classmethod
    def search_for_vars(cls, content: bytes, modules: set[str]) -> set[Var]:
        parsed = ast.parse(content.decode("utf-8"))
        v = cls(modules)
        v.visit(parsed)
        return v._found


class AllPythonConstantTargets(Collection[PythonConstantTarget]):
    pass


@rule
async def get_python_contant_targets(targets: AllTargets) -> AllPythonConstantTargets:
    return AllPythonConstantTargets(
        cast(PythonConstantTarget, target)
        for target in targets
        if target.has_field(PythonConstantSourceField)
    )


class BackwardMapping(FrozenDict[ResolveName, FrozenDict[str, Tuple[str, ...]]]):
    pass


@dataclass
class BackwardMappingRequest:
    addresses: Addresses


@rule
async def get_backward_mapping(
    python_contant_targets: AllPythonConstantTargets,
    mapping: FirstPartyPythonModuleMapping,
) -> BackwardMapping:
    paths = await MultiGet(
        Get(SourcesPaths, SourcesPathsRequest(tgt.get(PythonConstantSourceField)))
        for tgt in python_contant_targets
    )
    search_for = {file for path in paths for file in path.files}

    result: DefaultDict[str, DefaultDict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    for resolve, m in mapping.resolves_to_modules_to_providers.items():
        for module, module_providers in m.items():
            for module_provider in module_providers:
                filename = module_provider.addr.filename
                if filename in search_for:
                    result[resolve][filename].append(module)

    return BackwardMapping(
        FrozenDict(
            (
                resolve,
                FrozenDict((filename, tuple(sorted(modules))) for filename, modules in m.items()),
            )
            for resolve, m in result.items()
        )
    )


@rule
async def infer_python_dependencies_on_python_constants(
    request: InferPythonDependenciesOnPythonConstantsRequest,
    python_setup: PythonSetup,
    python_contant_targets: AllPythonConstantTargets,
    mapping: FirstPartyPythonModuleMapping,
    backward_mapping: BackwardMapping,
) -> InferredDependencies:
    """Infers dependencies on PythonConstantTarget-s based on python source imports."""

    sources = await Get(HydratedSources, HydrateSourcesRequest(request.field_set.source))
    digest_files = await Get(DigestContents, Digest, sources.snapshot.digest)
    content = digest_files[0].content
    resolve = request.field_set.resolve.normalized_value(python_setup)
    assert resolve is not None, "resolve is None"

    if not backward_mapping:
        raise ValueError("empty backward mapping")

    paths = await MultiGet(
        Get(SourcesPaths, SourcesPathsRequest(tgt.get(PythonConstantSourceField)))
        for tgt in python_contant_targets
    )
    logger.debug("backward mapping %s", backward_mapping)
    interesting_modules = {
        module
        for path in paths
        for filename in path.files
        for module in backward_mapping[resolve][filename]
    }

    logger.debug("interesting_modules %s", interesting_modules)
    vars = ImportVisitor.search_for_vars(content, interesting_modules)
    logger.debug("vars %s", vars)

    filenames_to_python_contant_targets: DefaultDict[str, List[PythonConstantTarget]] = defaultdict(
        list
    )
    for path, target in zip(paths, python_contant_targets):
        for filename in path.files:
            filenames_to_python_contant_targets[filename].append(target)

    include = set()
    for var in vars:
        for provider in mapping.resolves_to_modules_to_providers[resolve][var.module]:
            targets = filenames_to_python_contant_targets[provider.addr.filename]
            for target in targets:
                name = target.get(PythonConstantNameField).value
                logger.debug("check for var %s %s", name, var.name)
                if name == var.name:
                    include.add(target.address)

    logger.debug("include %s", include)
    return InferredDependencies(
        include=FrozenOrderedSet(include),
        exclude=FrozenOrderedSet(),
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GeneratePythonConstantTargetsRequest),
        UnionRule(InferDependenciesRequest, InferPythonDependenciesOnPythonConstantsRequest),
    )
