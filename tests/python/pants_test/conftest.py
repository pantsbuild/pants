# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

def pytest_sessionstart(session) -> None:
    # This is needed for `pants.util.docutil.pants_bin`, and needs to be defined very early in
    # pytests' lifecycle as `pants_bin` is used at import time to define static help strings.
    # (E.g. can't use an autouse, session-scoped fixture)
    os.environ["PANTS_BIN_NAME"] = "./pants"
