# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from pants.subsystem.subsystem import Subsystem

logger = logging.getLogger(__name__)


class TargetFilter(Subsystem):
    """Filter targets matching configured criteria.

    :API: public
    """

    options_scope = "target-filter"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        register(
            "--exclude-tags",
            type=list,
            default=[],
            fingerprint=True,
            help="Skip targets with given tag(s).",
        )

    def apply(self, targets):
        exclude_tags = set(self.get_options().exclude_tags)
        return TargetFiltering(exclude_tags).apply_tag_blacklist(targets)


class TargetFiltering:
    """Apply filtering logic against targets."""

    def __init__(self, exclude_tags):
        self.exclude_tags = exclude_tags

    def apply_tag_blacklist(self, targets):
        return [t for t in targets if not self.exclude_tags.intersection(t.tags)]
