# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pants.bsp.spec.base import TaskId
from pants.bsp.spec.notification import BSPNotification

# -----------------------------------------------------------------------------------------------
# Log message
# See https://build-server-protocol.github.io/docs/specification.html#log-message
# -----------------------------------------------------------------------------------------------


class MessageType(Enum):
    # An error message.
    ERROR = 1
    # A warning message.
    WARNING = 2
    # An information message.
    INFO = 3
    # A log message.
    LOG = 4


@dataclass(frozen=True)
class LogMessageParams(BSPNotification):
    notification_name = "build/logMessage"

    # The message type. See {@link MessageType}
    type_: MessageType

    # The actual message
    message: str

    # The task id if any.
    task: TaskId | None = None

    # The request id that originated this notification.
    origin_id: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "message": self.message,
            "type": self.type_.value,
        }
        if self.task is not None:
            result["task"] = self.task.to_json_dict()
        if self.origin_id is not None:
            result["originId"] = self.origin_id
        return result
