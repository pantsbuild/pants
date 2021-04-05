# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.shell.shunit2_test_runner import (
    Shunit2AlreadySourced,
    validate_source_shunit2_not_included,
)
from pants.engine.addresses import Address
from pants.engine.fs import FileContent


def test_validate_source_shunit2_not_included() -> None:
    def validate(content: str) -> None:
        validate_source_shunit2_not_included(
            FileContent("f.sh", content.encode()), Address("", target_name="t")
        )

    # These should be fine.
    validate("")
    validate("source another_file.sh\n")
    validate(". another_file.sh\n")

    # Invalid.
    def assert_error(content: str, *, lineno: int, line: str) -> None:
        with pytest.raises(Shunit2AlreadySourced) as exc:
            validate(content)
        assert (
            f"The test file f.sh sources shunit2 on line {lineno} with: {line}\n\n"
            f"Please remove this line so that Pants can run shunit2 for the target //:t"
        ) in str(exc.value)

    assert_error("source ./shunit2\n\necho 'foo'", lineno=1, line="source ./shunit2")
    assert_error(". ./shunit2\n\necho 'foo'", lineno=1, line=". ./shunit2")
    assert_error("source ../../shunit2\n\necho 'foo'", lineno=1, line="source ../../shunit2")
    assert_error(". ../../shunit2\n\necho 'foo'", lineno=1, line=". ../../shunit2")
    assert_error("echo 'foo'\n\nsource ./shunit2", lineno=3, line="source ./shunit2")
    assert_error("source ${HERE}/shunit2", lineno=1, line="source ${HERE}/shunit2")
    assert_error('source "${HERE}/shunit2"', lineno=1, line='source "${HERE}/shunit2"')
