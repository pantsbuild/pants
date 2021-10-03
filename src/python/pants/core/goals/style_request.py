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
from pants.engine.fs import EMPTY_DIGEST, Digest, Snapshot, Workspace
from pants.engine.target import FieldSet
from pants.util.meta import frozen_after_init
from pants.util.strutil import path_safe

logger = logging.getLogger(__name__)

_FS = TypeVar("_FS", bound=FieldSet)


@frozen_after_init
@dataclass(unsafe_hash=True)
class StyleRequest(Generic[_FS], EngineAwareParameter, metaclass=ABCMeta):
    """A request to style or lint a collection of `FieldSet`s.

    Should be subclassed for a particular style engine in order to support autoformatting or
    linting.
    """

    field_set_type: ClassVar[type[_FS]]

    field_sets: Collection[_FS]
    prior_formatter_result: Snapshot | None = None

    def __init__(
        self,
        field_sets: Iterable[_FS],
        *,
        prior_formatter_result: Snapshot | None = None,
    ) -> None:
        self.field_sets = Collection[_FS](field_sets)
        self.prior_formatter_result = prior_formatter_result

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
    get_tool_name: Callable[[_R], str],
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
        tool_name = get_tool_name(results).lower()  # type: ignore[arg-type]
        if len(results.results) == 1 and results.results[0].report != EMPTY_DIGEST:
            write_report(results.results[0].report, tool_name)
        else:
            for result in results.results:
                if result.report != EMPTY_DIGEST:
                    write_report(
                        result.report,
                        os.path.join(tool_name, path_safe(result.partition_description or "all")),
                    )
