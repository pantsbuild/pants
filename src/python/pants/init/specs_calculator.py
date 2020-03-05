# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from typing import Iterable, Optional

from pants.base.build_environment import get_buildroot, get_scm
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.specs import (
    AddressSpec,
    AddressSpecs,
    FilesystemSpec,
    FilesystemSpecs,
    SingleAddress,
    Specs,
)
from pants.engine.scheduler import SchedulerSession
from pants.option.options import Options
from pants.scm.subsystems.changed import ChangedAddresses, ChangedOptions, ChangedRequest
from pants.util.ordered_set import OrderedSet

logger = logging.getLogger(__name__)


class InvalidSpecConstraint(Exception):
    """Raised when invalid constraints are given via specs and arguments like --changed*."""


class SpecsCalculator:
    """Determines the specs for a given Pants run."""

    @classmethod
    def parse_specs(
        cls,
        raw_specs: Iterable[str],
        build_root: Optional[str] = None,
        exclude_patterns: Optional[Iterable[str]] = None,
        tags: Optional[Iterable[str]] = None,
    ) -> Specs:
        """Parse raw string specs into a Specs object."""
        build_root = build_root or get_buildroot()
        spec_parser = CmdLineSpecParser(build_root)

        address_specs: OrderedSet[AddressSpec] = OrderedSet()
        filesystem_specs: OrderedSet[FilesystemSpec] = OrderedSet()
        for spec_str in raw_specs:
            parsed_spec = spec_parser.parse_spec(spec_str)
            if isinstance(parsed_spec, AddressSpec):
                address_specs.add(parsed_spec)
            else:
                filesystem_specs.add(parsed_spec)

        address_specs_collection = AddressSpecs(
            dependencies=address_specs,
            exclude_patterns=exclude_patterns if exclude_patterns else tuple(),
            tags=tags,
        )
        filesystem_specs_collection = FilesystemSpecs(filesystem_specs)
        return Specs(
            address_specs=address_specs_collection, filesystem_specs=filesystem_specs_collection,
        )

    @classmethod
    def create(
        cls,
        options: Options,
        session: SchedulerSession,
        build_root: Optional[str] = None,
        exclude_patterns: Optional[Iterable[str]] = None,
        tags: Optional[Iterable[str]] = None,
    ) -> Specs:
        specs = cls.parse_specs(
            raw_specs=options.specs,
            build_root=build_root,
            exclude_patterns=exclude_patterns,
            tags=tags,
        )

        changed_options = ChangedOptions.from_options(options.for_scope("changed"))

        logger.debug("specs are: %s", specs)
        logger.debug("changed_options are: %s", changed_options)

        if changed_options.is_actionable() and specs.provided_specs.dependencies:
            # We've been provided both a change request and specs.
            raise InvalidSpecConstraint(
                "Multiple target selection methods provided. Please use only one of "
                "`--changed-*`, address specs, or filesystem specs."
            )

        if changed_options.is_actionable():
            scm = get_scm()
            if not scm:
                raise InvalidSpecConstraint(
                    "The `--changed-*` options are not available without a recognized SCM (usually Git)."
                )
            changed_request = ChangedRequest(
                sources=tuple(changed_options.changed_files(scm=scm)),
                include_dependees=changed_options.include_dependees,
            )
            (changed_addresses,) = session.product_request(ChangedAddresses, [changed_request])
            logger.debug("changed addresses: %s", changed_addresses.addresses)
            dependencies = tuple(
                SingleAddress(a.spec_path, a.target_name) for a in changed_addresses.addresses
            )
            return Specs(
                address_specs=AddressSpecs(
                    dependencies=dependencies, exclude_patterns=exclude_patterns, tags=tags,
                ),
                filesystem_specs=FilesystemSpecs([]),
            )

        return specs
