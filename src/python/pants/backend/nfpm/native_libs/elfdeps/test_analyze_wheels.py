# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PosixPath
from typing import cast

import pytest
import requests
from _pytest.tmpdir import TempPathFactory
from elfdeps import ELFAnalyzeSettings, ELFInfo, SOInfo  # pants: no-infer-dep
from pytest import fixture

from .analyze_wheels import WheelsELFInfo, analyze_wheel, analyze_wheels_repo

WHEELS = {
    # setproctitle has a native lib, and it's a small 31.2 kB file.
    "setproctitle-1.3.6-cp311-cp311-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl": {
        "uri": "https://files.pythonhosted.org/packages/cc/41/fbf57ec52f4f0776193bd94334a841f0bc9d17e745f89c7790f336420c65/setproctitle-1.3.6-cp311-cp311-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
        "results": (
            ELFInfo(
                filename=PosixPath("setproctitle/_setproctitle.cpython-311-x86_64-linux-gnu.so"),
                requires=[
                    SOInfo("libc.so.6", "GLIBC_2.2.5", "(64bit)"),
                    SOInfo("libpthread.so.0", "", "(64bit)"),
                    SOInfo("libc.so.6", "", "(64bit)"),
                    SOInfo("rtld", "GNU_HASH", ""),
                ],
                provides=[SOInfo("_setproctitle.cpython-311-x86_64-linux-gnu.so", "", "(64bit)")],
                machine="EM_X86_64",
                is_dso=True,
                is_exec=True,
                got_debug=False,
                got_hash=False,
                got_gnuhash=True,
                soname="_setproctitle.cpython-311-x86_64-linux-gnu.so",
                interp=None,
                marker="(64bit)",
                runpath=None,
            ),
        ),
    },
}
WHEELS_ELF_INFO = WheelsELFInfo(
    provides=(SOInfo("_setproctitle.cpython-311-x86_64-linux-gnu.so", "", "(64bit)"),),
    requires=(
        SOInfo("libc.so.6", "", "(64bit)"),
        SOInfo("libc.so.6", "GLIBC_2.2.5", "(64bit)"),
        SOInfo("libpthread.so.0", "", "(64bit)"),
        SOInfo("rtld", "GNU_HASH", ""),
    ),
)
WHEELS_ELF_INFO_DICT = {
    "provides": ["_setproctitle.cpython-311-x86_64-linux-gnu.so()(64bit)"],
    "requires": [
        "libc.so.6()(64bit)",
        "libc.so.6(GLIBC_2.2.5)(64bit)",
        "libpthread.so.0()(64bit)",
        "rtld(GNU_HASH)",
    ],
}
WHEELS_ELF_INFO_JSON = """{\
    "provides": ["_setproctitle.cpython-311-x86_64-linux-gnu.so()(64bit)"],
    "requires": [\
        "libc.so.6()(64bit)",\
        "libc.so.6(GLIBC_2.2.5)(64bit)",\
        "libpthread.so.0()(64bit)",\
        "rtld(GNU_HASH)"\
    ]}\
""".replace(" ", "")


@fixture(scope="module")
def wheels_repo(tmp_path_factory: TempPathFactory):
    wheels_repo_path = tmp_path_factory.mktemp("wheels_repo")
    for wheel_filename, wheel_info in WHEELS.items():
        assert wheel_filename.endswith(".whl")
        wheel_uri: str = cast(str, wheel_info["uri"])
        wheel_path = wheels_repo_path / wheel_filename
        wheel_response = requests.get(wheel_uri)
        wheel_response.raise_for_status()
        wheel_path.write_bytes(wheel_response.content)

    return wheels_repo_path


def test_wheels_elf_info_to_dict():
    assert WHEELS_ELF_INFO.to_dict() == WHEELS_ELF_INFO_DICT


def test_wheels_elf_info_to_json():
    assert WHEELS_ELF_INFO.to_json() == WHEELS_ELF_INFO_JSON


@pytest.mark.parametrize(
    "wheel_filename,expected",
    (
        pytest.param(wheel_filename, wheel_info["results"], id=wheel_filename)
        for wheel_filename, wheel_info in WHEELS.items()
    ),
)
def test_analyze_wheel(wheels_repo, wheel_filename, expected) -> None:
    wheel_path = wheels_repo / wheel_filename
    settings = ELFAnalyzeSettings(unique=True)
    results = tuple(analyze_wheel(wheel_path, settings))
    assert results == expected


def test_analyze_wheels_repo(wheels_repo) -> None:
    result = analyze_wheels_repo(wheels_repo)
    assert result == WHEELS_ELF_INFO
