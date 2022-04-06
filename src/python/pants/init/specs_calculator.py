# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from typing import cast

from pants.base.build_environment import get_git
from pants.base.specs import AddressLiteralSpec, AddressSpecs, FilesystemSpecs, Specs
from pants.base.specs_parser import SpecsParser
from pants.engine.addresses import AddressInput
from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.internals.selectors import Params
from pants.engine.rules import QueryRule
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.vcs.changed import ChangedAddresses, ChangedOptions, ChangedRequest

logger = logging.getLogger(__name__)


class InvalidSpecConstraint(Exception):
    """Raised when invalid constraints are given via specs and arguments like --changed*."""


def calculate_specs(
    options_bootstrapper: OptionsBootstrapper,
    options: Options,
    session: SchedulerSession,
) -> Specs:
    """Determine the specs for a given Pants run."""
    specs = SpecsParser().parse_specs(options.specs)
    changed_options = ChangedOptions.from_options(options.for_scope("changed"))

    logger.debug("specs are: %s", specs)
    logger.debug("changed_options are: %s", changed_options)

    if specs.provided and changed_options.provided:
        changed_name = "--changed-since" if changed_options.since else "--changed-diffspec"
        if specs.filesystem_specs and specs.address_specs:
            specs_description = "target and file/directory arguments"
        elif specs.filesystem_specs:
            specs_description = "file/directory arguments"
        else:
            specs_description = "target arguments"
        raise InvalidSpecConstraint(
            f"You used `{changed_name}` at the same time as using {specs_description}. Please "
            "use only one."
        )

    if not changed_options.provided:
        return specs

    git = get_git()
    if not git:
        raise InvalidSpecConstraint(
            "The `--changed-*` options are only available if Git is used for the repository."
        )
    changed_request = ChangedRequest(
        sources=tuple(changed_options.changed_files(git)),
        dependees=changed_options.dependees,
    )
    (changed_addresses,) = session.product_request(
        ChangedAddresses, [Params(changed_request, options_bootstrapper)]
    )
    logger.debug("changed addresses: %s", changed_addresses)

    address_specs = []
    for address in cast(ChangedAddresses, changed_addresses):
        address_input = AddressInput.parse(address.spec)
        address_specs.append(
            AddressLiteralSpec(
                path_component=address_input.path_component,
                target_component=address_input.target_component,
                generated_component=address_input.generated_component,
                parameters=address_input.parameters,
            )
        )
    return Specs(
        AddressSpecs(address_specs, filter_by_global_options=True),
        FilesystemSpecs([]),
        from_change_detection=True,
    )


def rules():
    return [
        QueryRule(ChangedAddresses, [ChangedRequest]),
    ]
