# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any, ClassVar


class BSPNotification:
    """Base class for all notifications so that a notification carries its RPC method name."""

    notification_name: ClassVar[str]

    def to_json_dict(self) -> dict[str, Any]:
        raise NotImplementedError
