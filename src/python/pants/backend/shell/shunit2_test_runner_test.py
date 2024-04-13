# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.shell.shunit2_test_runner import Shunit2FieldSet, add_source_shunit2
from pants.backend.shell.target_types import (
    Shunit2TestSourceField,
    Shunit2TestTarget,
    SkipShunit2TestsField,
)
from pants.engine.addresses import Address
from pants.engine.fs import FileContent


@pytest.mark.parametrize(
    ["original", "expected"],
    [
        # Not already in the file.
        ("", "source ./shunit2"),
        ("source another_file.sh\n", "source another_file.sh\nsource ./shunit2"),
        (". another_file.sh\n", ". another_file.sh\nsource ./shunit2"),
        # Overwrite what's already there.
        ("source ./shunit2\necho 'foo'", "source ./shunit2\necho 'foo'"),
        (". ./shunit2\necho 'foo'", "source ./shunit2\necho 'foo'"),
        ("source ../../shunit2\necho 'foo'", "source ./shunit2\necho 'foo'"),
        (". ../../shunit2\necho 'foo'", "source ./shunit2\necho 'foo'"),
        ("echo 'foo'\nsource ./shunit2", "echo 'foo'\nsource ./shunit2"),
        ("echo 'foo'; source ./shunit2", "echo 'foo'; source ./shunit2"),
        ("source ${HERE}/shunit2", "source ./shunit2"),
        ("source '${HERE}/shunit2'", "source ./shunit2"),
        ('source "${HERE}/shunit2"', "source ./shunit2"),
    ],
)
def test_add_source_shunit2(original: str, expected: str) -> None:
    result = add_source_shunit2(FileContent("f.sh", original.encode()), "shunit2").content.decode()
    print(result)
    assert result == expected


@pytest.mark.parametrize("skipped", (True, False))
def test_skip_tests(skipped: bool) -> None:
    tgt = Shunit2TestTarget(
        {Shunit2TestSourceField.alias: "tests.sh", SkipShunit2TestsField.alias: skipped},
        Address("tests"),
    )
    if skipped:
        assert not Shunit2FieldSet.is_applicable(tgt)
    else:
        assert Shunit2FieldSet.is_applicable(tgt)
