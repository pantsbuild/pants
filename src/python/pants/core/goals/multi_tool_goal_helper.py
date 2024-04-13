# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os.path
from typing import Iterable, Mapping, Protocol, Sequence, TypeVar

from pants.core.util_rules.distdir import DistDir
from pants.engine.fs import EMPTY_DIGEST, Digest, Workspace
from pants.option.option_types import IntOption, SkipOption, StrListOption
from pants.util.strutil import path_safe, softwrap

logger = logging.getLogger(__name__)


class SkippableSubsystem(Protocol):
    options_scope: str
    skip: SkipOption


class OnlyOption(StrListOption):
    """An --only option to select a subset of applicable tools."""

    def __new__(cls, tool_description: str, example1: str, example2: str):
        return super().__new__(
            cls,  # type: ignore[arg-type]
            "--only",
            help=lambda cls: softwrap(
                f"""
                Only run these {tool_description}s and skip all others.

                The {tool_description} names are outputted at the final summary of running this goal,
                e.g. `{example1}` and `{example2}`. You can also run `{cls.name} --only=fake` to
                get a list of all activated {tool_description}s.

                You can repeat this option, e.g. `{cls.name} --only={example1} --only={example2}` or
                `{cls.name} --only=['{example1}', '{example2}']`.
                """
            ),
        )


class BatchSizeOption(IntOption):
    """A --batch-size option to help with caching tool runs."""

    def __new__(cls, uppercase: str, lowercase: str):
        return super().__new__(
            cls,  # type: ignore[arg-type]
            "--batch-size",
            advanced=True,
            default=128,  # type: ignore[arg-type]
            help=softwrap(
                f"""
                The target number of files to be included in each {lowercase} batch.

                {uppercase} processes are batched for a few reasons:

                  1. to avoid OS argument length limits (in processes which don't support argument files)
                  2. to support more stable cache keys than would be possible if all files were operated \
                     on in a single batch.
                  3. to allow for parallelism in {lowercase} processes which don't have internal \
                     parallelism, or -- if they do support internal parallelism -- to improve scheduling \
                     behavior when multiple processes are competing for cores and so internal \
                     parallelism cannot be used perfectly.

                In order to improve cache hit rates (see 2.), batches are created at stable boundaries,
                and so this value is only a "target" batch size (rather than an exact value).
                """
            ),
        )


def determine_specified_tool_ids(
    goal_name: str,
    only_option: Iterable[str],
    all_requests: Iterable[type],
) -> set[str]:
    all_valid_ids = {request.tool_id for request in all_requests}  # type: ignore[attr-defined]
    if not only_option:
        return all_valid_ids

    specified = set(only_option)
    unrecognized_names = specified - all_valid_ids
    if unrecognized_names:
        plural = (
            ("s", repr(sorted(unrecognized_names)))
            if len(unrecognized_names) > 1
            else ("", repr(next(iter(unrecognized_names))))
        )
        raise ValueError(
            softwrap(
                f"""
                Unrecognized name{plural[0]} with the option `--{goal_name}-only`: {plural[1]}

                All valid names: {sorted(all_valid_ids)}
                """
            )
        )
    return specified


class _ResultWithReport(Protocol):
    @property
    def report(self) -> Digest:
        ...

    @property
    def partition_description(self) -> str | None:
        ...


class _ResultsWithReports(Protocol):
    @property
    def results(self) -> Sequence[_ResultWithReport]:
        ...


_R = TypeVar("_R", bound=_ResultsWithReports)


def write_reports(
    results_by_tool_name: Mapping[str, Sequence[_ResultWithReport]],
    workspace: Workspace,
    dist_dir: DistDir,
    *,
    goal_name: str,
) -> None:
    disambiguated_dirs: set[str] = set()

    def write_report(digest: Digest, subdir: str) -> None:
        while subdir in disambiguated_dirs:
            # It's unlikely that two distinct partition descriptions will become the
            # same after path_safe(), but might as well be safe.
            subdir += "_"
        disambiguated_dirs.add(subdir)
        output_dir = str(dist_dir.relpath / goal_name / subdir)
        workspace.write_digest(digest, path_prefix=output_dir)
        logger.info(f"Wrote {goal_name} report files to {output_dir}.")

    for tool_name, results in results_by_tool_name.items():
        if len(results) == 1 and results[0].report != EMPTY_DIGEST:
            write_report(results[0].report, tool_name)
        else:
            for result in results:
                if result.report != EMPTY_DIGEST:
                    write_report(
                        result.report,
                        os.path.join(tool_name, path_safe(result.partition_description or "all")),
                    )
