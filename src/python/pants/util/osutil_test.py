# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.util.osutil import OS_ALIASES, known_os_names, normalize_os_name


def test_alias_normalization() -> None:
    for normal_os, aliases in OS_ALIASES.items():
        for alias in aliases:
            assert normal_os == normalize_os_name(alias)


def test_keys_in_aliases() -> None:
    for key in OS_ALIASES.keys():
        assert key in known_os_names()


def test_no_warnings_on_known_names(caplog) -> None:
    for name in known_os_names():
        normalize_os_name(name)
        assert len(caplog.records) == 0


def test_warnings_on_unknown_names(caplog) -> None:
    name = "I really hope no one ever names an operating system with this string."
    normalize_os_name(name)
    assert len(caplog.records) == 1
    assert "Unknown operating system name" in caplog.text
