# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Optional

from pants.base.exiter import ExitCode
from pants.base.specs import Specs
from pants.option.options import Options


class SessionLifecycleHandler:
    def on_session_start(self):
        pass

    def on_session_end(self, *, engine_result: ExitCode):
        pass


class ExtensionLifecycleHandler:
    # Returns a SessionLifecycleHandler that will receive lifecycle events for the session.
    def on_session_create(
        self, *, build_root: str, options: Options, specs: Specs
    ) -> Optional[SessionLifecycleHandler]:
        pass
