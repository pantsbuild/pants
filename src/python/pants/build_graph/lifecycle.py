# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Optional

from pants.option.options import Options


class SessionLifecycleHandler:
    def on_session_start(self):
        pass

    def on_session_end(self):
        pass


class ExtensionLifecycleHandler:
    # Returns a SessionLifecycleHandler that will receive lifecycle events for the session.
    def on_session_create(self, options: Options) -> Optional[SessionLifecycleHandler]:
        pass
