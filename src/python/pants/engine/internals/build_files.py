# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import Any, Dict

from pants.base.exceptions import ResolveError
from pants.base.specs import AddressSpecs
from pants.engine.addresses import Address, Addresses, AddressInput, BuildFileAddress
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import DigestContents, GlobMatchErrorBehavior, PathGlobs, Paths
from pants.engine.internals.mapper import AddressFamily, AddressMap, AddressSpecsFilter
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser, error_on_imports
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import WrappedTarget
from pants.option.global_options import GlobalOptions
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import OrderedSet


@dataclass(frozen=True)
class BuildFileOptions:
    patterns: tuple[str, ...]
    ignores: tuple[str, ...]
    prelude_globs: tuple[str, ...]


@rule
def extract_build_file_options(global_options: GlobalOptions) -> BuildFileOptions:
    return BuildFileOptions(
        patterns=tuple(global_options.options.build_patterns),
        ignores=tuple(global_options.options.build_ignore),
        prelude_globs=tuple(global_options.options.build_file_prelude_globs),
    )


@rule(desc="Expand macros")
async def evaluate_preludes(build_file_options: BuildFileOptions) -> BuildFilePreludeSymbols:
    prelude_digest_contents = await Get(
        DigestContents,
        PathGlobs(
            build_file_options.prelude_globs,
            glob_match_error_behavior=GlobMatchErrorBehavior.ignore,
        ),
    )
    values: Dict[str, Any] = {}
    for file_content in prelude_digest_contents:
        try:
            file_content_str = file_content.content.decode()
            content = compile(file_content_str, file_content.path, "exec")
            exec(content, values)
        except Exception as e:
            raise Exception(f"Error parsing prelude file {file_content.path}: {e}")
        error_on_imports(file_content_str, file_content.path)
    # __builtins__ is a dict, so isn't hashable, and can't be put in a FrozenDict.
    # Fortunately, we don't care about it - preludes should not be able to override builtins, so we just pop it out.
    # TODO: Give a nice error message if a prelude tries to set a expose a non-hashable value.
    values.pop("__builtins__", None)
    return BuildFilePreludeSymbols(FrozenDict(values))


@rule
async def resolve_address(address_input: AddressInput) -> Address:
    # Determine the type of the path_component of the input.
    if address_input.path_component:
        paths = await Get(Paths, PathGlobs(globs=(address_input.path_component,)))
        is_file, is_dir = bool(paths.files), bool(paths.dirs)
    else:
        # It is an address in the root directory.
        is_file, is_dir = False, True

    if is_file:
        return address_input.file_to_address()
    elif is_dir:
        return address_input.dir_to_address()
    else:
        spec = address_input.path_component
        if address_input.target_component:
            spec += f":{address_input.target_component}"
        raise ResolveError(
            f"The file or directory '{address_input.path_component}' does not exist on disk in the "
            f"workspace, so the address '{spec}' cannot be resolved."
        )


@dataclass(frozen=True)
class AddressFamilyDir(EngineAwareParameter):
    """The directory to find addresses for.

    This does _not_ recurse into subdirectories.
    """

    path: str

    def debug_hint(self) -> str:
        return self.path


@rule(desc="Search for addresses in BUILD files")
async def parse_address_family(
    parser: Parser,
    build_file_options: BuildFileOptions,
    prelude_symbols: BuildFilePreludeSymbols,
    directory: AddressFamilyDir,
) -> AddressFamily:
    """Given an AddressMapper and a directory, return an AddressFamily.

    The AddressFamily may be empty, but it will not be None.
    """
    digest_contents = await Get(
        DigestContents,
        PathGlobs(
            globs=(
                *(os.path.join(directory.path, p) for p in build_file_options.patterns),
                *(f"!{p}" for p in build_file_options.ignores),
            )
        ),
    )
    if not digest_contents:
        raise ResolveError(f"Directory '{directory.path}' does not contain any BUILD files.")

    address_maps = [
        AddressMap.parse(fc.path, fc.content.decode(), parser, prelude_symbols)
        for fc in digest_contents
    ]
    return AddressFamily.create(directory.path, address_maps)


@rule
async def find_build_file(address: Address) -> BuildFileAddress:
    address_family = await Get(AddressFamily, AddressFamilyDir(address.spec_path))
    owning_address = address.maybe_convert_to_target_generator()
    if address_family.get_target_adaptor(owning_address) is None:
        raise ResolveError.did_you_mean(
            bad_name=owning_address.target_name,
            known_names=address_family.target_names,
            namespace=address_family.namespace,
        )
    bfa = next(
        build_file_address
        for build_file_address in address_family.build_file_addresses
        if build_file_address.address == owning_address
    )
    return BuildFileAddress(address, bfa.rel_path) if address.is_generated_target else bfa


@rule
async def find_target_adaptor(address: Address) -> TargetAdaptor:
    """Hydrate a TargetAdaptor so that it may be converted into the Target API."""
    if address.is_generated_target:
        raise AssertionError(
            "Generated targets are not defined in BUILD files, and so do not have "
            f"TargetAdaptors: {address}"
        )
    address_family = await Get(AddressFamily, AddressFamilyDir(address.spec_path))
    target_adaptor = address_family.get_target_adaptor(address)
    if target_adaptor is None:
        raise ResolveError.did_you_mean(
            bad_name=address.target_name,
            known_names=address_family.target_names,
            namespace=address_family.namespace,
        )
    return target_adaptor


@rule
def setup_address_specs_filter(global_options: GlobalOptions) -> AddressSpecsFilter:
    opts = global_options.options
    return AddressSpecsFilter(tags=opts.tag, exclude_target_regexps=opts.exclude_target_regexp)


@rule
async def addresses_from_address_specs(
    address_specs: AddressSpecs,
    build_file_options: BuildFileOptions,
    specs_filter: AddressSpecsFilter,
) -> Addresses:
    matched_addresses: OrderedSet[Address] = OrderedSet()
    filtering_disabled = address_specs.filter_by_global_options is False

    # Resolve all `AddressLiteralSpec`s. Will error on invalid addresses.
    literal_wrapped_targets = await MultiGet(
        Get(
            WrappedTarget,
            AddressInput(spec.path_component, spec.target_component, spec.generated_component),
        )
        for spec in address_specs.literals
    )
    matched_addresses.update(
        wrapped_tgt.target.address
        for wrapped_tgt in literal_wrapped_targets
        if filtering_disabled or specs_filter.matches(wrapped_tgt.target)
    )

    # Then, convert all `AddressGlobSpecs`. Resolve all BUILD files covered by the specs, then
    # group by directory.
    paths = await Get(
        Paths,
        PathGlobs,
        address_specs.to_path_globs(
            build_patterns=build_file_options.patterns,
            build_ignore_patterns=build_file_options.ignores,
        ),
    )
    dirnames = {os.path.dirname(f) for f in paths.files}
    address_families = await MultiGet(Get(AddressFamily, AddressFamilyDir(d)) for d in dirnames)
    address_family_by_directory = {af.namespace: af for af in address_families}

    for glob_spec in address_specs.globs:
        # These may raise ResolveError, depending on the type of spec.
        addr_families_for_spec = glob_spec.matching_address_families(address_family_by_directory)
        addr_target_pairs_for_spec = glob_spec.matching_addresses(addr_families_for_spec)
        matched_addresses.update(
            addr
            for (addr, tgt) in addr_target_pairs_for_spec
            # TODO(#11123): handle the edge case if a generated target's `tags` != its generator's.
            if filtering_disabled or specs_filter.matches_tgt_adaptor(addr, tgt)
        )

    return Addresses(sorted(matched_addresses))


def rules():
    return collect_rules()
