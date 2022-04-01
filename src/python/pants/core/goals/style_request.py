# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os.path
from abc import ABCMeta
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Generic, Iterable, Sequence, TypeVar

from typing_extensions import Protocol

from pants.core.util_rules.distdir import DistDir
from pants.engine.collection import Collection
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import EMPTY_DIGEST, Digest, Workspace
from pants.engine.target import FieldSet
from pants.util.meta import frozen_after_init
from pants.util.strutil import path_safe

logger = logging.getLogger(__name__)

_FS = TypeVar("_FS", bound=FieldSet)


def only_option_help(goal_name: str, tool_description: str, example1: str, example2: str) -> str:
    return (
        f"Only run these {tool_description}s and skip all others.\n\n"
        f"The {tool_description} names are outputted at the final summary of running this goal, "
        f"e.g. `{example1}` and `{example2}`. You can also run `{goal_name} --only=fake` to "
        f"get a list of all activated {tool_description}s.\n\n"
        f"You can repeat this option, e.g. `{goal_name} --only={example1} --only={example2}` or "
        f"`{goal_name} --only=['{example1}', '{example2}']`."
    )


def determine_specified_tool_names(
    goal_name: str,
    only_option: Iterable[str],
    all_style_requests: Iterable[type[StyleRequest]],
    *,
    extra_valid_names: Iterable[str] = (),
) -> set[str]:
    target_request_names = {request.name for request in all_style_requests}
    all_valid_names = {*target_request_names, *extra_valid_names}
    if not only_option:
        return all_valid_names

    specified = set(only_option)
    unrecognized_names = specified - all_valid_names
    if unrecognized_names:
        plural = (
            ("s", repr(sorted(unrecognized_names)))
            if len(unrecognized_names) > 1
            else ("", repr(next(iter(unrecognized_names))))
        )
        raise ValueError(
            f"Unrecognized name{plural[0]} with the option `--{goal_name}-only`: {plural[1]}\n\n"
            f"All valid names: {sorted(all_valid_names)}"
        )
    return specified


def style_batch_size_help(uppercase: str, lowercase: str) -> str:
    return (
        f"The target number of files to be included in each {lowercase} batch.\n"
        "\n"
        f"{uppercase} processes are batched for a few reasons:\n"
        "\n"
        "1. to avoid OS argument length limits (in processes which don't support argument "
        "files)\n"
        "2. to support more stable cache keys than would be possible if all files were "
        "operated on in a single batch.\n"
        f"3. to allow for parallelism in {lowercase} processes which don't have internal "
        "parallelism, or -- if they do support internal parallelism -- to improve scheduling "
        "behavior when multiple processes are competing for cores and so internal "
        "parallelism cannot be used perfectly.\n"
        "\n"
        "In order to improve cache hit rates (see 2.), batches are created at stable boundaries, "
        'and so this value is only a "target" batch size (rather than an exact value).'
    )


@frozen_after_init
@dataclass(unsafe_hash=True)
class StyleRequest(Generic[_FS], EngineAwareParameter, metaclass=ABCMeta):
    """A request to format or lint a collection of `FieldSet`s.

    Should be subclassed for a particular style engine in order to support autoformatting or
    linting.
    """

    field_set_type: ClassVar[type[_FS]]
    name: ClassVar[str]

    field_sets: Collection[_FS]

    def __init__(
        self,
        field_sets: Iterable[_FS],
    ) -> None:
        self.field_sets = Collection[_FS](field_sets)

    def debug_hint(self) -> str:
        return self.name

    def metadata(self) -> dict[str, Any]:
        return {"addresses": [fs.address.spec for fs in self.field_sets]}


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
    all_results: tuple[_ResultsWithReports, ...],
    workspace: Workspace,
    dist_dir: DistDir,
    *,
    goal_name: str,
    get_name: Callable[[_R], str],
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

    for results in all_results:
        tool_name = get_name(results).lower()  # type: ignore[arg-type]
        if len(results.results) == 1 and results.results[0].report != EMPTY_DIGEST:
            write_report(results.results[0].report, tool_name)
        else:
            for result in results.results:
                if result.report != EMPTY_DIGEST:
                    write_report(
                        result.report,
                        os.path.join(tool_name, path_safe(result.partition_description or "all")),
                    )
