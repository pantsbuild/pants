# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.python.rules.targets import Timeout
from pants.build_graph.address import Address


def test_timeout_validation() -> None:
    with pytest.raises(ValueError):
        Timeout(-100, address=Address.parse(":tests"))
    with pytest.raises(ValueError):
        Timeout(0, address=Address.parse(":tests"))
    assert Timeout(5, address=Address.parse(":tests")).value == 5
