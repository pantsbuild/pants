# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from typing import cast

from pants.base.deprecated import warn_or_error
from pants.base.specs import AddressLiteralSpec, FileLiteralSpec, RawSpecs, Specs
from pants.base.specs_parser import SpecsParser
from pants.core.util_rules.system_binaries import GitBinary, GitBinaryRequest
from pants.engine.addresses import AddressInput
from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.internals.selectors import Params
from pants.engine.rules import QueryRule
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.docutil import bin_name
from pants.util.strutil import softwrap
from pants.vcs.changed import ChangedAddresses, ChangedOptions, ChangedRequest
from pants.vcs.git import GitWorktreeRequest, MaybeGitWorktree

logger = logging.getLogger(__name__)


class InvalidSpecConstraint(Exception):
    """Raised when invalid constraints are given via specs and arguments like --changed*."""


def calculate_specs(
    options_bootstrapper: OptionsBootstrapper,
    options: Options,
    session: SchedulerSession,
) -> Specs:
    """Determine the specs for a given Pants run."""
    global_options = options.for_global_scope()
    unmatched_cli_globs = global_options.unmatched_cli_globs.to_glob_match_error_behavior()
    convert_dir_literal_to_address_literal = (
        global_options.use_deprecated_directory_cli_args_semantics
    )
    if global_options.is_default("use_deprecated_directory_cli_args_semantics"):
        warn_or_error(
            "2.14.0.dev0",
            "`use_deprecated_directory_cli_args_semantics` defaulting to True",
            softwrap(
                f"""
                Currently, a directory argument like `{bin_name()} test dir` is shorthand for the
                target `dir:dir`, i.e. the target that leaves off `name=`.

                In Pants 2.14, by default, a directory argument will instead match all
                targets/files in the directory.

                To opt into the new and more intuitive semantics early, set
                `use_deprecated_directory_cli_args_semantics = false` in the `[GLOBAL]` section in
                `pants.toml`. Otherwise, set to `true` to silence this warning.
                """
            ),
        )
    specs = SpecsParser().parse_specs(
        options.specs,
        description_of_origin="CLI arguments",
        unmatched_glob_behavior=unmatched_cli_globs,
        convert_dir_literal_to_address_literal=convert_dir_literal_to_address_literal,
    )

    changed_options = ChangedOptions.from_options(options.for_scope("changed"))
    logger.debug("specs are: %s", specs)
    logger.debug("changed_options are: %s", changed_options)

    if specs and changed_options.provided:
        changed_name = "--changed-since" if changed_options.since else "--changed-diffspec"
        specs_description = specs.arguments_provided_description()
        assert specs_description is not None
        raise InvalidSpecConstraint(
            f"You used `{changed_name}` at the same time as using {specs_description}. You can "
            f"only use `{changed_name}` or use normal arguments."
        )

    if not changed_options.provided:
        return specs

    (git_binary,) = session.product_request(GitBinary, [Params(GitBinaryRequest())])
    (maybe_git_worktree,) = session.product_request(
        MaybeGitWorktree, [Params(GitWorktreeRequest(), git_binary)]
    )
    if not maybe_git_worktree.git_worktree:
        raise InvalidSpecConstraint(
            "The `--changed-*` options are only available if Git is used for the repository."
        )

    changed_files = tuple(changed_options.changed_files(maybe_git_worktree.git_worktree))
    file_literal_specs = tuple(FileLiteralSpec(f) for f in changed_files)

    changed_request = ChangedRequest(changed_files, changed_options.dependees)
    (changed_addresses,) = session.product_request(
        ChangedAddresses, [Params(changed_request, options_bootstrapper)]
    )
    logger.debug("changed addresses: %s", changed_addresses)

    address_literal_specs = []
    for address in cast(ChangedAddresses, changed_addresses):
        address_input = AddressInput.parse(address.spec, description_of_origin="`--changed-since`")
        address_literal_specs.append(
            AddressLiteralSpec(
                path_component=address_input.path_component,
                target_component=address_input.target_component,
                generated_component=address_input.generated_component,
                parameters=address_input.parameters,
            )
        )

    return Specs(
        includes=RawSpecs(
            # We need both address_literals and file_literals to cover all our edge cases, including
            # target-aware vs. target-less goals, e.g. `list` vs `count-loc`.
            address_literals=tuple(address_literal_specs),
            file_literals=file_literal_specs,
            unmatched_glob_behavior=unmatched_cli_globs,
            filter_by_global_options=True,
            from_change_detection=True,
            description_of_origin="`--changed-since`",
        ),
        ignores=RawSpecs(description_of_origin="`--changed-since`"),
    )


def rules():
    return [
        QueryRule(ChangedAddresses, [ChangedRequest]),
        QueryRule(GitBinary, [GitBinaryRequest]),
        QueryRule(MaybeGitWorktree, [GitWorktreeRequest, GitBinary]),
    ]
