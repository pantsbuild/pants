# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.build_graph.address import Address
from pants.engine.internals.target_adaptor import TargetAdaptor


@pytest.mark.parametrize(
    "tgt_adaptor_name,expected",
    (
        ("tgt", Address("", target_name="tgt")),
        ("tgt@k=v", Address("", target_name="tgt", parameters={"k": "v"})),
        ("tgt@k1=v,k2=v", Address("", target_name="tgt", parameters={"k1": "v", "k2": "v"})),
    ),
)
def test_target_adaptor_to_address(tgt_adaptor_name: str, expected: Address) -> None:
    assert TargetAdaptor("some_tgt_alias", tgt_adaptor_name).to_address("") == expected
