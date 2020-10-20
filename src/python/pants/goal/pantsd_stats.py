# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class PantsDaemonStats:
    """Tracks various stats about the daemon."""

    scheduler_metrics: Dict[str, int] = field(default_factory=dict)

    def set_scheduler_metrics(self, scheduler_metrics: Dict[str, int]) -> None:
        self.scheduler_metrics = scheduler_metrics

    def set_target_root_size(self, size):
        self.scheduler_metrics["target_root_size"] = size

    def set_affected_targets_size(self, size):
        self.scheduler_metrics["affected_targets_size"] = size

    def get_all(self) -> Dict[str, int]:
        for key in ["target_root_size", "affected_targets_size"]:
            self.scheduler_metrics.setdefault(key, 0)
        return self.scheduler_metrics
