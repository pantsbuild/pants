# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional

from pants.util.osutil import (
    OS_ALIASES,
    get_closest_mac_host_platform_pair,
    known_os_names,
    normalize_os_name,
)


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


def test_get_closest_mac_host_platform_pair() -> None:
    # Note the gaps in darwin versions.
    platform_name_map = {
        ("linux", "x86_64"): ("linux", "x86_64"),
        ("linux", "amd64"): ("linux", "x86_64"),
        ("darwin", "10"): ("mac", "10.6"),
        ("darwin", "13"): ("mac", "10.9"),
        ("darwin", "14"): ("mac", "10.10"),
        ("darwin", "16"): ("mac", "10.12"),
        ("darwin", "17"): ("mac", "10.13"),
    }

    def get_macos_version(darwin_version: Optional[str]) -> Optional[str]:
        host, version = get_closest_mac_host_platform_pair(
            darwin_version, platform_name_map=platform_name_map
        )
        if host is not None:
            assert "mac" == host
        return version

    assert "10.13" == get_macos_version("19")
    assert "10.13" == get_macos_version("18")
    assert "10.13" == get_macos_version("17")
    assert "10.12" == get_macos_version("16")
    assert "10.10" == get_macos_version("15")
    assert "10.10" == get_macos_version("14")
    assert "10.9" == get_macos_version("13")
    assert "10.6" == get_macos_version("12")
    assert "10.6" == get_macos_version("11")
    assert "10.6" == get_macos_version("10")
    assert get_macos_version("9") is None

    # When a version bound of `None` is provided, it should select the most recent OSX platform
    # available.
    assert "10.13" == get_macos_version(None)
