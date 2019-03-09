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
from pants.engine.addresses import Addresses
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.query import (
    QueryAddresses,
    QueryComponentWrapper,
    QueryParseInput,
    QueryPipeline,
    QueryPipelineRequest,
)
from pants.engine.selectors import Params
from pants.option.options import Options
from pants.scm.subsystems.changed import (
    ChangedAddresses,
    ChangedOptions,
    ChangedRequest,
    UncachedScmWrapper,
)
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
        # Determine the literal specs.
        specs = cls.parse_specs(
            raw_specs=options.specs,
            build_root=build_root,
            exclude_patterns=exclude_patterns,
            tags=tags,
        )

        # Determine `Changed` arguments directly from options to support pre-`Subsystem`
        # initialization paths.
        changed_options = ChangedOptions.from_options(options.for_scope("changed"))

        # Parse --query expressions into objects which can be resolved into BuildFileAddresses via v2
        # rules.
        query_expr_strings = options.for_global_scope().query
        exprs = session.product_request(
            QueryComponentWrapper, [QueryParseInput(s) for s in query_expr_strings]
        )
        exprs = [ex.underlying for ex in exprs]

        logger.debug("specs are: %s", specs)
        logger.debug("changed_options are: %s", changed_options)
        logger.debug("query exprs are: %s (%s)", exprs, bool(exprs))
        targets_specified = sum(
            1
            for item in (changed_options.is_actionable(), specs.provided_specs.dependencies)
            if item
        )

        if targets_specified > 1:
            # We've been provided more than one of: a change request, an owner request, a query request,
            # or spec roots.
            raise InvalidSpecConstraint(
                "Multiple target selection methods provided. Please use only one of "
                "`--changed-*`, `--owner-of`, `--query`, address specs, or filesystem specs."
            )

        def scm(entity):
            scm = get_scm()
            if not scm:
                raise InvalidSpecConstraint(
                    # TODO: centralize the error messaging for when an SCM is required, and describe what SCMs
                    # are supported!
                    "{} are not available without a recognized SCM (usually git).".format(entity)
                )
            return scm

        if changed_options.is_actionable():
            # We've been provided no spec roots (e.g. `./pants list`) AND a changed request. Compute
            # alternate target roots.
            scm = scm("The --changed-* options")
            if not scm:
                raise InvalidSpecConstraint(
                    "The `--changed-*` options are not available without a recognized SCM (usually Git)."
                )
            changed_request = ChangedRequest(
                sources=tuple(changed_options.changed_files(scm=scm)),
                dependees=changed_options.dependees,
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

        # TODO(#7346): deprecate --owner-of and --changed-* in favor of --query versions, allow
        # pipelining of successive query expressions with the command-line target specs as the initial
        # input!
        if exprs:
            # TODO: this should only be necessary for the `changed-since`/etc queries! This can be done by
            # returning a dummy ScmWrapper if no `changed-*` queries are used!
            scm = scm("The --query option")

            (input_addresses,) = session.product_request(Addresses, [specs.provided_specs])
            (query_output,) = session.product_request(
                QueryAddresses,
                [
                    Params(
                        UncachedScmWrapper.create(scm),
                        QueryPipelineRequest(
                            pipeline=QueryPipeline(tuple(exprs)), input_addresses=input_addresses,
                        ),
                    )
                ],
            )

            expr_addresses = query_output.addresses
            logger.debug("expr addresses: %s", expr_addresses)
            dependencies = tuple(SingleAddress(a.spec_path, a.target_name) for a in expr_addresses)
            return Specs(
                address_specs=AddressSpecs(
                    dependencies=dependencies, exclude_patterns=exclude_patterns, tags=tags
                ),
                filesystem_specs=FilesystemSpecs([]),
            )

        return specs
