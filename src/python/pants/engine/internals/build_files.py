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
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from pprint import pformat
from typing import Any, Mapping, Sequence, cast

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
from pants.engine.fs import (
    DigestContents,
    FileContent,
    GlobMatchErrorBehavior,
    PathGlobs,
    Paths,
    Snapshot,
)
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
    SourcesField,
)
from pants.engine.unions import UnionMembership
from pants.init.bootstrap_scheduler import BootstrapStatus
from pants.option.global_options import GlobalOptions, UnmatchedBuildFileGlobs
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
        env_vars.update(BUILDFilePreProcessor.get_env_vars(file_content))
    # __builtins__ is a dict, so isn't hashable, and can't be put in a FrozenDict.
    # Fortunately, we don't care about it - preludes should not be able to override builtins, so we just pop it out.
    # TODO: Give a nice error message if a prelude tries to set a expose a non-hashable value.
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


class BUILDFilePreProcessor(ast.NodeVisitor):
    def __init__(self, filename: str):
        super().__init__()
        self.env_vars: set[str] = set()
        self.hash_sources: dict[
            tuple[int, int], list[tuple[str | tuple[str, str], ...]]
        ] = defaultdict(list)
        self.filename = filename

    @classmethod
    def create(cls, file_content: FileContent) -> BUILDFilePreProcessor:
        obj = cls(file_content.path)
        try:
            obj.visit(ast.parse(file_content.content, file_content.path))
        except SyntaxError as e:
            raise BuildFileSyntaxError.from_syntax_error(e).with_traceback(e.__traceback__)
        else:
            return obj

    @classmethod
    def get_env_vars(cls, file_content: FileContent) -> Sequence[str]:
        obj = cls.create(file_content)
        return tuple(obj.env_vars)

    @staticmethod
    def node_value(node: ast.AST) -> str | None:
        if sys.version_info[0:2] < (3, 8):
            return node.s if isinstance(node, ast.Str) else None
        else:
            return node.value if isinstance(node, ast.Constant) else None

    def visit_Call(self, node: ast.Call):
        func_name = isinstance(node.func, ast.Name) and node.func.id
        if func_name:
            visit_func = getattr(self, f"visit_{func_name}_Call", self.generic_visit)
            visit_func(node)
        else:
            self.generic_visit(node)

    def visit_env_Call(self, node: ast.Call):
        """Extract referenced environment variables from `env(..)` calls."""
        is_env = True
        for arg in node.args:
            if not is_env:
                self.visit(arg)
                continue

            # Only first arg may be checked as env name
            is_env = False

            value = self.node_value(arg)
            if value:
                self.env_vars.add(value)
            else:
                logger.warning(
                    f"{self.filename}:{arg.lineno}: Only constant string values as variable name to "
                    f"`env()` is currently supported. This `env()` call will always result in "
                    "the default value only."
                )

        for kwarg in node.keywords:
            self.visit(kwarg)

    def visit_pants_hash_Call(self, node: ast.Call):
        """Extract referenced source globs or target types from `pants_hash(..)` calls."""
        values = []
        linenos = set()
        value: tuple[str, str] | str | None = None

        for arg in node.args:
            if isinstance(arg, ast.Name):
                value = ("target_type", arg.id)
            else:
                value = self.node_value(arg)
            if value:
                values.append(value)
                linenos.add(arg.lineno)
            else:
                logger.warning(
                    f"{self.filename}:{arg.lineno}: Only constant string values and target types "
                    "may be used for `pants_hash()`."
                )
        # Track glob values per line range in the BUILD file to give good error messages.
        self.hash_sources[(min(linenos), max(linenos))].append(tuple(values))

        for kwarg in node.keywords:
            self.visit(kwarg)


async def _get_build_file_referenced_data(
    file_content: FileContent,
    extra_env: Sequence[str],
    env: CompleteEnvironmentVars,
    glob_match_error_behavior: GlobMatchErrorBehavior,
    registered_target_types: RegisteredTargetTypes,
    union_membership: UnionMembership,
) -> tuple[EnvironmentVars, Mapping[tuple[str, ...], str]]:
    pp = BUILDFilePreProcessor.create(file_content)
    dirpath = os.path.dirname(pp.filename)

    def _fix_glob(glob: str) -> str:
        if glob.startswith("/"):
            return glob[1:]
        if glob.startswith("!/"):
            return f"!{glob[2:]}"
        return SourcesField.prefix_glob_with_dirpath(dirpath, glob)

    def _globs_with_description_of_origin(
        globs: tuple[str | tuple[str, str], ...], origin: tuple[int, int]
    ) -> tuple[tuple[tuple[str, tuple[str, ...]], ...], str]:
        description_of_origin = (
            f"{pp.filename}:{origin[0] if origin[0] == origin[1] else '-'.join(map(str, origin))}"
        )
        # We track the list of globs to match paired with the original value provided (in case of a target alias).
        _globs: list[tuple[str, tuple[str, ...]]] = []
        for glob in globs:
            if isinstance(glob, str):
                _globs.append((glob, (glob,)))
                continue
            if isinstance(glob, tuple) and len(glob) == 2 and glob[0] == "target_type":
                target_type = registered_target_types.aliases_to_types.get(glob[1])
                if target_type:
                    default_globs = target_type.class_get_field(
                        SourcesField, union_membership
                    ).default
                    if isinstance(default_globs, str):
                        default_globs = (default_globs,)
                    _globs.append((target_type.alias, default_globs or ()))
                    continue
            logger.warning(f"{description_of_origin}: Invalid argument to `pants_hash`: {glob!r}")

        return tuple(_globs), description_of_origin

    glob_origins = [
        _globs_with_description_of_origin(globs, origin)
        for origin, all_globs in pp.hash_sources.items()
        for globs in all_globs
    ]
    env_vars = (*pp.env_vars, *extra_env)
    env_var_values, *snapshots = await MultiGet(
        Get(
            EnvironmentVars,
            {
                EnvironmentVarsRequest(sorted(env_vars)): EnvironmentVarsRequest,
                env: CompleteEnvironmentVars,
            },
        ),
        *(
            Get(
                Snapshot,
                PathGlobs(
                    globs=(  # Extracting all globs to match.
                        _fix_glob(g) for _, gs in globs for g in gs
                    ),
                    glob_match_error_behavior=glob_match_error_behavior,
                    description_of_origin=f"{origin} in `pants_hash(...)` call",
                ),
            )
            for globs, origin in glob_origins
        ),
    )
    pants_hashes = {}
    for (globs, _), snapshot in zip(glob_origins, snapshots):
        # Extracting the original glob value for the key.
        key = tuple(g for g, _ in globs)
        pants_hashes[key] = snapshot.digest.fingerprint
        logger.debug(
            f"pants_hash{key}: {snapshot.digest.fingerprint}, files:\n" + pformat(snapshot.files)
        )

    return (
        env_var_values,
        pants_hashes,
    )


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
    unmatched_build_file_globs: UnmatchedBuildFileGlobs,
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

    pre_processed_data = [
        await _get_build_file_referenced_data(
            file_content=fc,
            extra_env=prelude_symbols.referenced_env_vars,
            env=session_values[CompleteEnvironmentVars],
            glob_match_error_behavior=unmatched_build_file_globs.error_behavior,
            registered_target_types=registered_target_types,
            union_membership=union_membership,
        )
        for fc in digest_contents
    ]

    address_maps = [
        AddressMap.parse(
            fc.path,
            fc.content.decode(),
            parser,
            prelude_symbols,
            env_vars,
            pants_hashes,
            bootstrap_status.in_progress,
            defaults_parser_state,
            dependents_rules_parser_state,
            dependencies_rules_parser_state,
        )
        for fc, (env_vars, pants_hashes) in zip(digest_contents, pre_processed_data)
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
