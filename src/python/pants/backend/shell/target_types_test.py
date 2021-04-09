# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.shell.target_types import Shunit2Shell


@pytest.mark.parametrize(
    ["content", "expected"],
    [
        # Direct paths.
        (b"#!/path/to/sh", Shunit2Shell.sh),
        (b"#!/path/to/bash", Shunit2Shell.bash),
        (b"#!/path/to/dash", Shunit2Shell.dash),
        (b"#!/path/to/ksh", Shunit2Shell.ksh),
        (b"#!/path/to/pdksh", Shunit2Shell.pdksh),
        (b"#!/path/to/zsh", Shunit2Shell.zsh),
        # `env $shell`.
        (b"#!/path/to/env sh", Shunit2Shell.sh),
        (b"#!/path/to/env bash", Shunit2Shell.bash),
        (b"#!/path/to/env dash", Shunit2Shell.dash),
        (b"#!/path/to/env ksh", Shunit2Shell.ksh),
        (b"#!/path/to/env pdksh", Shunit2Shell.pdksh),
        (b"#!/path/to/env zsh", Shunit2Shell.zsh),
        # Whitespace is fine.
        (b"#! /path/to/env sh", Shunit2Shell.sh),
        (b"#!/path/to/env   sh", Shunit2Shell.sh),
        (b"#!/path/to/env sh ", Shunit2Shell.sh),
        (b"#!/path/to/sh arg1 arg2 ", Shunit2Shell.sh),
        (b"#!/path/to/env sh\n", Shunit2Shell.sh),
        # Must be absolute path.
        (b"#!/sh", Shunit2Shell.sh),
        (b"#!sh", None),
        # Missing or invalid shebang.
        (b"", None),
        (b"some program", None),
        (b"something #!/path/to/sh", None),
        (b"something #!/path/to/env sh", None),
        (b"\n#!/path/to/sh", None),
    ],
)
def test_shunit2_shell_parse_shebang(content: bytes, expected: Shunit2Shell | None) -> None:
    result = Shunit2Shell.parse_shebang(content)
    if expected is None:
        assert result is None
    else:
        assert result == expected
