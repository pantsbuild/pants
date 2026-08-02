# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.engine.fs import FileDigest
from pants.jvm.resolve.coordinate import Coordinate
from pants.jvm.subsystems import JvmSubsystem, NailgunServer
from pants.testutil.option_util import create_subsystem

_DEFAULT_SERVER = "com.martiansoftware:nailgun-server:0.9.1#com.martiansoftware.nailgun.NGServer"
_DEFAULT_DIGEST = "4518faa6bf4bd26fccdc4d85e1625dc679381a08d56872d8ad12151dda9cef25:32927"


def test_nailgun_server_parses() -> None:
    jvm = create_subsystem(
        JvmSubsystem, nailgun_server=_DEFAULT_SERVER, nailgun_jar_digest=_DEFAULT_DIGEST
    )
    assert jvm.nailgun_server == NailgunServer(
        coordinate=Coordinate(
            group="com.martiansoftware", artifact="nailgun-server", version="0.9.1"
        ),
        main_class="com.martiansoftware.nailgun.NGServer",
        file_digest=FileDigest(
            fingerprint="4518faa6bf4bd26fccdc4d85e1625dc679381a08d56872d8ad12151dda9cef25",
            serialized_bytes_length=32927,
        ),
    )
    assert jvm.nailgun_server.file_name == "com.martiansoftware_nailgun-server_0.9.1.jar"


def test_nailgun_server_missing_main_class() -> None:
    jvm = create_subsystem(
        JvmSubsystem,
        nailgun_server="com.martiansoftware:nailgun-server:0.9.1",
        nailgun_jar_digest="ab:1",
    )
    with pytest.raises(ValueError, match="missing the main class"):
        _ = jvm.nailgun_server


def test_nailgun_server_invalid_coordinate() -> None:
    jvm = create_subsystem(
        JvmSubsystem, nailgun_server="not-a-coordinate#Main", nailgun_jar_digest="ab:1"
    )
    with pytest.raises(ValueError) as exc:
        _ = jvm.nailgun_server

    assert "[jvm].nailgun_server" in str(exc.value)
    assert "not-a-coordinate" in str(exc.value)


@pytest.mark.parametrize("digest", ["no-colon", "ab:notanumber", ":123", "ab:"])
def test_nailgun_jar_digest_invalid(digest: str) -> None:
    jvm = create_subsystem(
        JvmSubsystem,
        nailgun_server="com.martiansoftware:nailgun-server:0.9.1#Main",
        nailgun_jar_digest=digest,
    )
    with pytest.raises(ValueError, match="nailgun_jar_digest"):
        _ = jvm.nailgun_server
