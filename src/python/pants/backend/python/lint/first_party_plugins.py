# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import ClassVar, TypeVar

from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonRequirementsField,
    PythonResolveField,
)
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFilesRequest,
    strip_python_sources,
)
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest
from pants.engine.internals.graph import resolve_unparsed_address_inputs
from pants.engine.internals.graph import transitive_targets as transitive_targets_get
from pants.engine.intrinsics import add_prefix
from pants.engine.rules import implicitly
from pants.engine.target import TransitiveTargetsRequest
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


@dataclass(frozen=True)
class BaseFirstPartyPlugins:
    requirement_strings: FrozenOrderedSet[str]
    interpreter_constraints_and_resolve_fields: FrozenOrderedSet[
        tuple[InterpreterConstraintsField, PythonResolveField]
    ]
    sources_digest: Digest

    PREFIX: ClassVar[str] = "__plugins"

    def __bool__(self) -> bool:
        return self.sources_digest != EMPTY_DIGEST


FPP = TypeVar("FPP", bound=BaseFirstPartyPlugins)


async def resolve_first_party_plugins(
    source_plugins: UnparsedAddressInputs, fpp_type: type[FPP]
) -> FPP:
    if not source_plugins:
        return fpp_type(FrozenOrderedSet(), FrozenOrderedSet(), EMPTY_DIGEST)

    plugin_target_addresses = await resolve_unparsed_address_inputs(source_plugins, **implicitly())
    transitive_targets = await transitive_targets_get(
        TransitiveTargetsRequest(plugin_target_addresses), **implicitly()
    )

    requirements_fields: OrderedSet[PythonRequirementsField] = OrderedSet()
    interpreter_constraints_and_resolve_fields: OrderedSet[
        tuple[InterpreterConstraintsField, PythonResolveField]
    ] = OrderedSet()
    for tgt in transitive_targets.closure:
        if tgt.has_field(PythonRequirementsField):
            requirements_fields.add(tgt[PythonRequirementsField])
        if tgt.has_field(InterpreterConstraintsField):
            interpreter_constraints_and_resolve_fields.add(
                (tgt[InterpreterConstraintsField], tgt[PythonResolveField])
            )

    # NB: Flake8 source plugins must be explicitly loaded via PYTHONPATH (i.e. PEX_EXTRA_SYS_PATH).
    # The value must point to the plugin's directory, rather than to a parent's directory, because
    # `flake8:local-plugins` values take a module name rather than a path to the module;
    # i.e. `plugin`, but not `path/to/plugin`.
    # (This means users must have specified the parent directory as a source root.)
    stripped_sources = await strip_python_sources(
        **implicitly(PythonSourceFilesRequest(transitive_targets.closure))
    )
    prefixed_sources = await add_prefix(
        AddPrefix(stripped_sources.stripped_source_files.snapshot.digest, fpp_type.PREFIX)
    )

    return fpp_type(
        requirement_strings=PexRequirements.req_strings_from_requirement_fields(
            requirements_fields,
        ),
        interpreter_constraints_and_resolve_fields=FrozenOrderedSet(
            interpreter_constraints_and_resolve_fields
        ),
        sources_digest=prefixed_sources,
    )
