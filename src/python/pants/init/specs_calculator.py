# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from pathlib import PurePath
from typing import Iterable, Optional, cast

from pants.base.build_environment import get_buildroot, get_scm
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.specs import (
    AddressSpec,
    AddressSpecs,
    FilesystemLiteralSpec,
    FilesystemSpec,
    FilesystemSpecs,
    SingleAddress,
    Specs,
)
from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.query import QueryAddresses, QueryComponentWrapper, QueryParseInput
from pants.engine.selectors import Params
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.scm.git import Git
from pants.scm.subsystems.changed import (
    ChangedAddresses,
    ChangedFiles,
    ChangedFilesRequest,
    ChangedOptions,
    ChangedRequest,
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
        options_bootstrapper: OptionsBootstrapper,
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

        # Parse --query expressions into objects which can be resolved into BuildFileAddresses via
        # v2 rules.
        query_expr_strings = options.for_global_scope().query

        logger.debug("specs are: %s", specs)
        logger.debug("changed_options are: %s", changed_options)
        logger.debug("query exprs are: %s", query_expr_strings)

        if specs.provided and changed_options.provided:
            changed_name = "--changed-since" if changed_options.since else "--changed-diffspec"
            if specs.filesystem_specs and specs.address_specs:
                specs_description = "target and file arguments"
            elif specs.filesystem_specs:
                specs_description = "file arguments"
            else:
                specs_description = "target arguments"
            raise InvalidSpecConstraint(
                f"You used `{changed_name}` at the same time as using {specs_description}. Please "
                "use only one."
            )

        if not (changed_options.provided or query_expr_strings):
            return specs

        git = get_scm()
        if not git:
            raise InvalidSpecConstraint(
                "{} are not available without a recognized SCM (currently just git)."
            )
        assert isinstance(git, Git)
        (changed_files,) = session.product_request(ChangedFiles, [
            Params(ChangedFilesRequest(changed_options, git=git))])
        changed_request = ChangedRequest(
            sources=tuple(changed_files),
            dependees=changed_options.dependees,
        )
        (changed_addresses,) = session.product_request(
            ChangedAddresses, [Params(changed_request, options_bootstrapper)]
        )
        logger.debug("changed addresses: %s", changed_addresses)

        address_specs = []
        filesystem_specs = []
        for address in cast(ChangedAddresses, changed_addresses):
            if address.generated_base_target_name:
                file_name = PurePath(address.spec_path, address.target_name).as_posix()
                filesystem_specs.append(FilesystemLiteralSpec(file_name))
            else:
                address_specs.append(SingleAddress(address.spec_path, address.target_name))


        if query_expr_strings:
            # TODO(#7346): deprecate --owner-of and --changed-* in favor of --query versions, allow
            # pipelining of successive query expressions with the command-line target specs as the
            # initial input!
            if len(query_expr_strings) > 1:
                raise ValueError("Only one --query argument is currently supported! "
                                 f"Received: {query_expr_strings}.")

            # TODO: allow returning @union types to avoid this double synchronous engine invocation!
            exprs = session.product_request(
                QueryComponentWrapper, [QueryParseInput(s) for s in query_expr_strings]
            )
            exprs = [ex.underlying for ex in exprs]

            (expr_addresses,) = session.product_request(
                QueryAddresses, [Params(git, exprs[0], options_bootstrapper)]
            )
            logger.debug("expr addresses: %s", expr_addresses)
            dependencies = tuple(
                SingleAddress(a.spec_path, a.target_name) for a in expr_addresses
            )
            return Specs(
                address_specs=AddressSpecs(
                    dependencies=dependencies, exclude_patterns=exclude_patterns, tags=tags
                ),
                filesystem_specs=FilesystemSpecs(filesystem_specs),
            )

        return Specs(
            address_specs=AddressSpecs(
                address_specs, exclude_patterns=exclude_patterns, tags=tags,
            ),
            filesystem_specs=FilesystemSpecs(filesystem_specs),
        )
