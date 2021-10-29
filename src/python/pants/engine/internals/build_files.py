# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os.path
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from pants.base.exceptions import ResolveError
from pants.base.specs import AddressSpecs
from pants.engine.addresses import Address, Addresses, AddressInput, BuildFileAddress
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import DigestContents, GlobMatchErrorBehavior, PathGlobs, Paths
from pants.engine.internals.mapper import AddressFamily, AddressMap, AddressSpecsFilter
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser, error_on_imports
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Targets, UnexpandedTargets, WrappedTarget
from pants.option.global_options import GlobalOptions
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import OrderedSet


@dataclass(frozen=True)
class BuildFileOptions:
    patterns: tuple[str, ...]
    ignores: tuple[str, ...] = ()
    prelude_globs: tuple[str, ...] = ()


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
    values: dict[str, Any] = {}
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
    if not address_specs.globs:
        return Addresses(matched_addresses)

    # Resolve all `AddressGlobSpecs`.
    build_file_paths = await Get(
        Paths,
        PathGlobs,
        address_specs.to_build_file_path_globs(
            build_patterns=build_file_options.patterns,
            build_ignore_patterns=build_file_options.ignores,
        ),
    )
    dirnames = {os.path.dirname(f) for f in build_file_paths.files}
    address_families = await MultiGet(Get(AddressFamily, AddressFamilyDir(d)) for d in dirnames)
    candidate_addresses = Addresses(
        itertools.chain.from_iterable(
            address_family.addresses_to_target_adaptors for address_family in address_families
        )
    )

    tgts_generators_kept, tgts_generators_replaced = await MultiGet(
        Get(UnexpandedTargets, Addresses, candidate_addresses),
        Get(Targets, Addresses, candidate_addresses),
    )
    residence_dir_to_targets = defaultdict(list)
    for tgt in (*tgts_generators_kept, *tgts_generators_replaced):
        residence_dir_to_targets[tgt.residence_dir].append(tgt)

    matched_globs = set()
    for glob_spec in address_specs.globs:
        for residence_dir in residence_dir_to_targets:
            if not glob_spec.matches(residence_dir):
                continue
            matched_globs.add(glob_spec)
            matched_addresses.update(
                tgt.address
                for tgt in residence_dir_to_targets[residence_dir]
                if filtering_disabled or specs_filter.matches(tgt)
            )

    unmatched_globs = [
        glob
        for glob in address_specs.globs
        if glob not in matched_globs and glob.error_if_no_matches
    ]
    if unmatched_globs:
        glob_description = (
            f"the address glob `{unmatched_globs[0]}`"
            if len(unmatched_globs) == 1
            else f"these address globs: {sorted(str(glob) for glob in unmatched_globs)}"
        )
        raise ResolveError(
            f"No targets found for {glob_description}\n\n"
            f"Do targets exist in those directories? Maybe run `./pants tailor` to generate "
            f"BUILD files? See {doc_url('targets')} about targets and BUILD files."
        )

    return Addresses(sorted(matched_addresses))


def rules():
    return collect_rules()
