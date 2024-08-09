# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import ContextManager, cast

import pytest

from pants.backend.nfpm.fields.contents import (
    NfpmContentFileModeField,
    _filemode_chars,
    _parse_filemode,
)
from pants.engine.internals.native_engine import Address
from pants.engine.target import InvalidFieldException
from pants.testutil.pytest_util import no_exception


@pytest.mark.parametrize(
    "filemode,expected",
    (
        # too short
        ("", pytest.raises(ValueError)),
        ("rwx", pytest.raises(ValueError)),
        ("rwx" * 2, pytest.raises(ValueError)),
        *(("-" * length, pytest.raises(ValueError)) for length in range(1, 9)),
        # bad chars
        ("RWX" * 2, pytest.raises(ValueError)),
        ("a--b--c--", pytest.raises(ValueError)),
        *((char * 9, pytest.raises(ValueError)) for char in _filemode_chars - {"-"}),
        # success
        ("---" * 3, 0),
        ("r--" * 3, 0o0444),
        ("-w-" * 3, 0o0222),
        ("--x" * 3, 0o0111),
        ("rw-" * 3, 0o0666),
        ("-wx" * 3, 0o0333),
        ("r-x" * 3, 0o0555),
        ("rwx" * 3, 0o0777),
        ("--s--s--t", 0o7111),
        ("--S--S--T", 0o7000),
        ("--s------", 0o4100),
        ("-----s---", 0o2010),
        ("--------t", 0o1001),
        ("--S------", 0o4000),
        ("-----S---", 0o2000),
        ("--------T", 0o1000),
        ("rwsrwsrwt", 0o7777),
    ),
)
def test_parse_filemode(filemode: str, expected: int | ContextManager):
    if isinstance(expected, int):
        raises = cast("ContextManager", no_exception())
    else:
        raises = expected

    with raises:
        result = _parse_filemode(filemode)
        assert result == expected


@pytest.mark.parametrize(
    "raw_value,expected",
    (
        # string
        ("0755", 0o755),
        ("777", 0o0777),
        ("0600", 0o600),
        ("0660", 0o660),
        ("0999", pytest.raises(InvalidFieldException)),
        ("07778", pytest.raises(InvalidFieldException)),
        # octal
        (0o0000, 0o0000),
        (0o0755, 0o0755),
        (0o0777, 0o0777),
        (0o17777, pytest.raises(InvalidFieldException)),
        (0o10000, pytest.raises(InvalidFieldException)),
        # int (why would people use int? ick. Oh well.)
        (0, 0o0000),
        (7, 0o0007),
        (8, 0o0010),
        (64, 0o0100),
        (384, 0o0600),
        (511, 0o0777),
        (4095, 0o7777),
        (4096, pytest.raises(InvalidFieldException)),
    ),
)
def test_file_mode_field_calculate_value(raw_value: int | str, expected: int | ContextManager):
    if isinstance(expected, int):
        raises = cast("ContextManager", no_exception())
    else:
        raises = expected

    address = Address("", target_name="tgt")
    with raises:
        result = NfpmContentFileModeField.compute_value(raw_value, address)
        assert result == expected
