# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import ast
import builtins
import itertools
import logging
import os.path
import sys
import typing
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Sequence, cast

from pants.build_graph.address import (
    Address,
    AddressInput,
    BuildFileAddress,
    BuildFileAddressRequest,
    MaybeAddress,
    ResolveError,
)
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.env_vars import CompleteEnvironmentVars, EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import DigestContents, FileContent, GlobMatchErrorBehavior, PathGlobs, Paths
from pants.engine.internals.defaults import BuildFileDefaults, BuildFileDefaultsParserState
from pants.engine.internals.dep_rules import (
    BuildFileDependencyRules,
    DependencyRuleApplication,
    MaybeBuildFileDependencyRulesImplementation,
)
from pants.engine.internals.mapper import AddressFamily, AddressMap
from pants.engine.internals.parser import (
    BuildFilePreludeSymbols,
    BuildFileSymbolsInfo,
    Parser,
    error_on_imports,
)
from pants.engine.internals.session import SessionValues
from pants.engine.internals.synthetic_targets import (
    SyntheticAddressMaps,
    SyntheticAddressMapsRequest,
)
from pants.engine.internals.target_adaptor import TargetAdaptor, TargetAdaptorRequest
from pants.engine.rules import Get, MultiGet, QueryRule, collect_rules, rule
from pants.engine.target import (
    DependenciesRuleApplication,
    DependenciesRuleApplicationRequest,
    RegisteredTargetTypes,
)
from pants.engine.unions import UnionMembership
from pants.init.bootstrap_scheduler import BootstrapStatus
from pants.option.global_options import GlobalOptions
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class BuildFileSyntaxError(SyntaxError):
    """An error parsing a BUILD file."""

    def from_syntax_error(error: SyntaxError) -> BuildFileSyntaxError:
        return BuildFileSyntaxError(
            error.msg,
            (
                error.filename,
                error.lineno,
                error.offset,
                error.text,
            ),
        )

    def __str__(self) -> str:
        first_line = f"Error parsing BUILD file {self.filename}:{self.lineno}: {self.msg}"
        # These two fields are optional per the spec, so we can't rely on them being set.
        if self.text is not None and self.offset is not None:
            second_line = f"  {self.text.rstrip()}"
            third_line = f"  {' ' * (self.offset - 1)}^"
            return f"{first_line}\n{second_line}\n{third_line}"

        return first_line


@dataclass(frozen=True)
class BuildFileOptions:
    patterns: tuple[str, ...]
    ignores: tuple[str, ...] = ()
    prelude_globs: tuple[str, ...] = ()


@rule
def extract_build_file_options(
    global_options: GlobalOptions,
    bootstrap_status: BootstrapStatus,
) -> BuildFileOptions:
    return BuildFileOptions(
        patterns=global_options.build_patterns,
        ignores=global_options.build_ignore,
        prelude_globs=(
            () if bootstrap_status.in_progress else global_options.build_file_prelude_globs
        ),
    )


@rule(desc="Expand macros")
async def evaluate_preludes(
    build_file_options: BuildFileOptions,
    parser: Parser,
) -> BuildFilePreludeSymbols:
    prelude_digest_contents = await Get(
        DigestContents,
        PathGlobs(
            build_file_options.prelude_globs,
            glob_match_error_behavior=GlobMatchErrorBehavior.ignore,
        ),
    )
    globals: dict[str, Any] = {
        **{name: getattr(builtins, name) for name in dir(builtins) if name.endswith("Error")},
        **{name: getattr(typing, name) for name in typing.__all__},
        # Ensure the globals for each prelude includes the builtin symbols (E.g. `python_sources`)
        # and any build file aliases (e.g. from plugins)
        **parser.symbols,
    }
    locals: dict[str, Any] = {}
    env_vars: set[str] = set()
    for file_content in prelude_digest_contents:
        try:
            file_content_str = file_content.content.decode()
            content = compile(file_content_str, file_content.path, "exec", dont_inherit=True)
            exec(content, globals, locals)
        except Exception as e:
            raise Exception(f"Error parsing prelude file {file_content.path}: {e}")
        error_on_imports(file_content_str, file_content.path)
        env_vars.update(BUILDFileEnvVarExtractor.get_env_vars(file_content))
    # __builtins__ is a dict, so isn't hashable, and can't be put in a FrozenDict.
    # Fortunately, we don't care about it - preludes should not be able to override builtins, so we just pop it out.
    # TODO: Give a nice error message if a prelude tries to set and expose a non-hashable value.
    locals.pop("__builtins__", None)
    # Ensure preludes can reference each other by populating the shared globals object with references
    # to the other symbols
    globals.update(locals)
    return BuildFilePreludeSymbols.create(locals, env_vars)


@rule
async def get_all_build_file_symbols_info(
    parser: Parser, prelude_symbols: BuildFilePreludeSymbols
) -> BuildFileSymbolsInfo:
    return BuildFileSymbolsInfo.from_info(
        parser.symbols_info.info.values(), prelude_symbols.info.values()
    )


@rule
async def maybe_resolve_address(address_input: AddressInput) -> MaybeAddress:
    # Determine the type of the path_component of the input.
    if address_input.path_component:
        paths = await Get(Paths, PathGlobs(globs=(address_input.path_component,)))
        is_file, is_dir = bool(paths.files), bool(paths.dirs)
    else:
        # It is an address in the root directory.
        is_file, is_dir = False, True

    if is_file:
        return MaybeAddress(address_input.file_to_address())
    if is_dir:
        return MaybeAddress(address_input.dir_to_address())
    spec = address_input.path_component
    if address_input.target_component:
        spec += f":{address_input.target_component}"
    return MaybeAddress(
        ResolveError(
            softwrap(
                f"""
                The file or directory '{address_input.path_component}' does not exist on disk in
                the workspace, so the address '{spec}' from {address_input.description_of_origin}
                cannot be resolved.
                """
            )
        )
    )


@rule
async def resolve_address(maybe_address: MaybeAddress) -> Address:
    if isinstance(maybe_address.val, ResolveError):
        raise maybe_address.val
    return maybe_address.val


@dataclass(frozen=True)
class AddressFamilyDir(EngineAwareParameter):
    """The directory to find addresses for.

    This does _not_ recurse into subdirectories.
    """

    path: str

    def debug_hint(self) -> str:
        return self.path


@dataclass(frozen=True)
class OptionalAddressFamily:
    path: str
    address_family: AddressFamily | None = None

    def ensure(self) -> AddressFamily:
        if self.address_family is not None:
            return self.address_family
        raise ResolveError(f"Directory '{self.path}' does not contain any BUILD files.")


@rule
async def ensure_address_family(request: OptionalAddressFamily) -> AddressFamily:
    return request.ensure()


class BUILDFileEnvVarExtractor(ast.NodeVisitor):
    def __init__(self, filename: str):
        super().__init__()
        self.env_vars: set[str] = set()
        self.filename = filename

    @classmethod
    def get_env_vars(cls, file_content: FileContent) -> Sequence[str]:
        obj = cls(file_content.path)
        try:
            obj.visit(ast.parse(file_content.content, file_content.path))
        except SyntaxError as e:
            raise BuildFileSyntaxError.from_syntax_error(e).with_traceback(e.__traceback__)

        return tuple(obj.env_vars)

    def visit_Call(self, node: ast.Call):
        is_env = isinstance(node.func, ast.Name) and node.func.id == "env"
        for arg in node.args:
            if not is_env:
                self.visit(arg)
                continue

            # Only first arg may be checked as env name
            is_env = False

            if sys.version_info[0:2] < (3, 8):
                value = arg.s if isinstance(arg, ast.Str) else None
            else:
                value = arg.value if isinstance(arg, ast.Constant) else None
            if value:
                # Found env name in this call, we're done here.
                self.env_vars.add(value)
                return
            else:
                logger.warning(
                    f"{self.filename}:{arg.lineno}: Only constant string values as variable name to "
                    f"`env()` is currently supported. This `env()` call will always result in "
                    "the default value only."
                )

        for kwarg in node.keywords:
            self.visit(kwarg)


@rule(desc="Search for addresses in BUILD files")
async def parse_address_family(
    parser: Parser,
    bootstrap_status: BootstrapStatus,
    build_file_options: BuildFileOptions,
    prelude_symbols: BuildFilePreludeSymbols,
    directory: AddressFamilyDir,
    registered_target_types: RegisteredTargetTypes,
    union_membership: UnionMembership,
    maybe_build_file_dependency_rules_implementation: MaybeBuildFileDependencyRulesImplementation,
    session_values: SessionValues,
) -> OptionalAddressFamily:
    """Given an AddressMapper and a directory, return an AddressFamily.

    The AddressFamily may be empty, but it will not be None.
    """
    digest_contents, all_synthetic_address_maps = await MultiGet(
        Get(
            DigestContents,
            PathGlobs(
                globs=(
                    *(os.path.join(directory.path, p) for p in build_file_options.patterns),
                    *(f"!{p}" for p in build_file_options.ignores),
                )
            ),
        ),
        Get(SyntheticAddressMaps, SyntheticAddressMapsRequest(directory.path)),
    )
    synthetic_address_maps = tuple(itertools.chain(all_synthetic_address_maps))
    if not digest_contents and not synthetic_address_maps:
        return OptionalAddressFamily(directory.path)

    defaults = BuildFileDefaults({})
    dependents_rules: BuildFileDependencyRules | None = None
    dependencies_rules: BuildFileDependencyRules | None = None
    parent_dirs = tuple(PurePath(directory.path).parents)
    if parent_dirs:
        maybe_parents = await MultiGet(
            Get(OptionalAddressFamily, AddressFamilyDir(str(parent_dir)))
            for parent_dir in parent_dirs
        )
        for maybe_parent in maybe_parents:
            if maybe_parent.address_family is not None:
                family = maybe_parent.address_family
                defaults = family.defaults
                dependents_rules = family.dependents_rules
                dependencies_rules = family.dependencies_rules
                break

    defaults_parser_state = BuildFileDefaultsParserState.create(
        directory.path, defaults, registered_target_types, union_membership
    )
    build_file_dependency_rules_class = (
        maybe_build_file_dependency_rules_implementation.build_file_dependency_rules_class
    )
    if build_file_dependency_rules_class is not None:
        dependents_rules_parser_state = build_file_dependency_rules_class.create_parser_state(
            directory.path,
            dependents_rules,
        )
        dependencies_rules_parser_state = build_file_dependency_rules_class.create_parser_state(
            directory.path,
            dependencies_rules,
        )
    else:
        dependents_rules_parser_state = None
        dependencies_rules_parser_state = None

    def _extract_env_vars(
        file_content: FileContent, extra_env: Sequence[str], env: CompleteEnvironmentVars
    ) -> Get[EnvironmentVars]:
        """For BUILD file env vars, we only ever consult the local systems env."""
        env_vars = (*BUILDFileEnvVarExtractor.get_env_vars(file_content), *extra_env)
        return Get(
            EnvironmentVars,
            {
                EnvironmentVarsRequest(env_vars): EnvironmentVarsRequest,
                env: CompleteEnvironmentVars,
            },
        )

    all_env_vars = await MultiGet(
        _extract_env_vars(
            fc, prelude_symbols.referenced_env_vars, session_values[CompleteEnvironmentVars]
        )
        for fc in digest_contents
    )

    address_maps = [
        AddressMap.parse(
            fc.path,
            fc.content.decode(),
            parser,
            prelude_symbols,
            env_vars,
            bootstrap_status.in_progress,
            defaults_parser_state,
            dependents_rules_parser_state,
            dependencies_rules_parser_state,
        )
        for fc, env_vars in zip(digest_contents, all_env_vars)
    ]

    # Freeze defaults and dependency rules
    frozen_defaults = defaults_parser_state.get_frozen_defaults()
    frozen_dependents_rules = cast(
        "BuildFileDependencyRules | None",
        dependents_rules_parser_state
        and dependents_rules_parser_state.get_frozen_dependency_rules(),
    )
    frozen_dependencies_rules = cast(
        "BuildFileDependencyRules | None",
        dependencies_rules_parser_state
        and dependencies_rules_parser_state.get_frozen_dependency_rules(),
    )

    # Process synthetic targets.
    for address_map in address_maps:
        for synthetic in synthetic_address_maps:
            synthetic.process_declared_targets(address_map)
            synthetic.apply_defaults(frozen_defaults)

    return OptionalAddressFamily(
        directory.path,
        AddressFamily.create(
            spec_path=directory.path,
            address_maps=(*address_maps, *synthetic_address_maps),
            defaults=frozen_defaults,
            dependents_rules=frozen_dependents_rules,
            dependencies_rules=frozen_dependencies_rules,
        ),
    )


@rule
async def find_build_file(request: BuildFileAddressRequest) -> BuildFileAddress:
    address = request.address
    address_family = await Get(AddressFamily, AddressFamilyDir(address.spec_path))
    owning_address = address.maybe_convert_to_target_generator()
    if address_family.get_target_adaptor(owning_address) is None:
        raise ResolveError.did_you_mean(
            owning_address,
            description_of_origin=request.description_of_origin,
            known_names=address_family.target_names,
            namespace=address_family.namespace,
        )
    bfa = next(
        build_file_address
        for build_file_address in address_family.build_file_addresses
        if build_file_address.address == owning_address
    )
    return BuildFileAddress(address, bfa.rel_path) if address.is_generated_target else bfa


def _get_target_adaptor(
    address: Address, address_family: AddressFamily, description_of_origin: str
) -> TargetAdaptor:
    target_adaptor = address_family.get_target_adaptor(address)
    if target_adaptor is None:
        raise ResolveError.did_you_mean(
            address,
            description_of_origin=description_of_origin,
            known_names=address_family.target_names,
            namespace=address_family.namespace,
        )
    return target_adaptor


@rule
async def find_target_adaptor(request: TargetAdaptorRequest) -> TargetAdaptor:
    """Hydrate a TargetAdaptor so that it may be converted into the Target API."""
    address = request.address
    if address.is_generated_target:
        raise AssertionError(
            "Generated targets are not defined in BUILD files, and so do not have "
            f"TargetAdaptors: {request}"
        )
    address_family = await Get(AddressFamily, AddressFamilyDir(address.spec_path))
    target_adaptor = _get_target_adaptor(address, address_family, request.description_of_origin)
    return target_adaptor


def _rules_path(address: Address) -> str:
    if address.is_file_target and os.path.sep in address.relative_file_path:  # type: ignore[operator]
        # The file is in a subdirectory of spec_path
        return os.path.dirname(address.filename)
    else:
        return address.spec_path


async def _get_target_family_and_adaptor_for_dep_rules(
    *addresses: Address, description_of_origin: str
) -> tuple[tuple[AddressFamily, TargetAdaptor], ...]:
    # Fetch up to 2 sets of address families per address, as we want the rules from the directory
    # the file is in rather than the directory where the target generator was declared, if not the
    # same.
    rules_paths = set(
        itertools.chain.from_iterable(
            {address.spec_path, _rules_path(address)} for address in addresses
        )
    )
    maybe_address_families = await MultiGet(
        Get(OptionalAddressFamily, AddressFamilyDir(rules_path)) for rules_path in rules_paths
    )
    maybe_families = {maybe.path: maybe for maybe in maybe_address_families}

    return tuple(
        (
            (
                maybe_families[_rules_path(address)].address_family
                or maybe_families[address.spec_path].ensure()
            ),
            _get_target_adaptor(
                address,
                maybe_families[address.spec_path].ensure(),
                description_of_origin,
            ),
        )
        for address in addresses
    )


@rule
async def get_dependencies_rule_application(
    request: DependenciesRuleApplicationRequest,
    maybe_build_file_rules_implementation: MaybeBuildFileDependencyRulesImplementation,
) -> DependenciesRuleApplication:
    build_file_dependency_rules_class = (
        maybe_build_file_rules_implementation.build_file_dependency_rules_class
    )
    if build_file_dependency_rules_class is None:
        return DependenciesRuleApplication.allow_all()

    (
        origin_rules_family,
        origin_target,
    ), *dependencies_family_adaptor = await _get_target_family_and_adaptor_for_dep_rules(
        request.address,
        *request.dependencies,
        description_of_origin=request.description_of_origin,
    )

    dependencies_rule: dict[Address, DependencyRuleApplication] = {}
    for dependency_address, (dependency_rules_family, dependency_target) in zip(
        request.dependencies, dependencies_family_adaptor
    ):
        dependencies_rule[
            dependency_address
        ] = build_file_dependency_rules_class.check_dependency_rules(
            origin_address=request.address,
            origin_adaptor=origin_target,
            dependencies_rules=origin_rules_family.dependencies_rules,
            dependency_address=dependency_address,
            dependency_adaptor=dependency_target,
            dependents_rules=dependency_rules_family.dependents_rules,
        )
    return DependenciesRuleApplication(request.address, FrozenDict(dependencies_rule))


def rules():
    return (
        *collect_rules(),
        # The `BuildFileSymbolsInfo` is consumed by the `HelpInfoExtracter` and uses the scheduler
        # session `product_request()` directly so we need an explicit QueryRule to provide this type
        # as an valid entrypoint into the rule graph.
        QueryRule(BuildFileSymbolsInfo, ()),
    )
