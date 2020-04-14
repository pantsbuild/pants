# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Iterator, List, Optional

from pants.option.ranked_value import Rank


# TODO: Get rid of this? The parser should be able to lazily track.
class OptionTracker:
    """Records a history of what options are set and where they came from."""

    @dataclass(frozen=True)
    class OptionHistoryRecord:
        value: str
        rank: Rank
        deprecation_version: Optional[str]
        details: Optional[str]

    class OptionHistory:
        """Tracks the history of an individual option."""

        def __init__(self) -> None:
            self.values: List["OptionTracker.OptionHistoryRecord"] = []

        def record_value(
            self,
            value: str,
            rank: Rank,
            deprecation_version: Optional[str],
            details: Optional[str] = None,
        ) -> None:
            """Record that the option was set to the given value at the given rank.

            :param value: the value the option was set to.
            :param rank: the rank of the option when it was set to this value.
            :param deprecation_version: Deprecation version for this option.
            :param details: optional elaboration of where the option came from (eg, a particular
              config file).
            """
            deprecation_version_to_write = deprecation_version

            if self.latest is not None:
                if self.latest.rank > rank:
                    return
                if self.latest.value == value:
                    return  # No change.
                if self.latest.deprecation_version:
                    # Higher RankedValue may not contain deprecation version, so this make sure
                    # deprecation_version propagate to later and higher ranked value since it is immutable
                    deprecation_version_to_write = (
                        self.latest.deprecation_version or deprecation_version
                    )

            self.values.append(
                OptionTracker.OptionHistoryRecord(
                    value, rank, deprecation_version_to_write, details
                )
            )

        @property
        def was_overridden(self) -> bool:
            """A value was overridden if it has rank greater than 'HARDCODED'."""
            if self.latest is None or len(self.values) < 2:
                return False
            return self.latest.rank > Rank.HARDCODED and self.values[-2].rank > Rank.NONE

        @property
        def latest(self) -> Optional["OptionTracker.OptionHistoryRecord"]:
            """The most recent value this option was set to, or None if it was never set."""
            return self.values[-1] if self.values else None

        def __iter__(self) -> Iterator["OptionTracker.OptionHistoryRecord"]:
            for record in self.values:
                yield record

        def __len__(self) -> int:
            return len(self.values)

    def __init__(self) -> None:
        self.option_history_by_scope: DefaultDict = defaultdict(dict)

    def record_option(
        self,
        scope: str,
        option: str,
        value: str,
        rank: Rank,
        deprecation_version: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        """Records that the given option was set to the given value.

        :param scope: scope of the option.
        :param option: name of the option.
        :param value: value the option was set to.
        :param rank: the rank of the option (Eg, Rank.HARDCODED), to keep track of where the
          option came from.
        :param deprecation_version: Deprecation version for this option.
        :param details: optional additional details about how the option was set (eg, the name
               of a particular config file, if the rank is Rank.CONFIG).
        """
        scoped_options = self.option_history_by_scope[scope]
        if option not in scoped_options:
            scoped_options[option] = self.OptionHistory()
        scoped_options[option].record_value(value, rank, deprecation_version, details)
