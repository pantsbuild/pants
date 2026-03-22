# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.internals.native_engine import FileDigest, PyNgOptionsReader
from pants.ng.external_binary import ExternalBinary
from pants.util.meta import classproperty
from pants.util.strutil import softwrap


def test_external_binary(tmp_path) -> None:
    class DummyBinary(ExternalBinary):
        options_scope = "dummy"
        help = "The dummy binary"
        version_default = "0.0.1"

        @classproperty
        def exe_default(cls):
            return "dummy_exe"

        known_versions_default = softwrap(
            """
        {
            "0.0.1": {
                "linux_x86_64": {
                    "url": "dummy_url1",
                    "sha256": "d9117a92856a41369888e8d8e823de3dceb86d7bb31f50c38fc1524bf409a308",
                    "size": 12345
                },
                "linux_arm64": {
                    "url": "dummy_url1",
                    "sha256": "d9117a92856a41369888e8d8e823de3dceb86d7bb31f50c38fc1524bf409a308",
                    "size": 12345
                },
                "macos_arm64": {
                    "url": "dummy_url1",
                    "sha256": "d9117a92856a41369888e8d8e823de3dceb86d7bb31f50c38fc1524bf409a308",
                    "size": 12345
                }
            },
            "0.0.2": {
                "linux_x86_64": {
                    "url": "dummy_url2",
                    "sha256": "ae79f70c751f957b1ce1d619a180953ae8900f4031fd0b7a1c239a5416bc58af",
                    "size": 999
                },
                "linux_arm64": {
                    "url": "dummy_url2",
                    "sha256": "ae79f70c751f957b1ce1d619a180953ae8900f4031fd0b7a1c239a5416bc58af",
                    "size": 999
                },
                "macos_arm64": {
                    "url": "dummy_url2",
                    "sha256": "ae79f70c751f957b1ce1d619a180953ae8900f4031fd0b7a1c239a5416bc58af",
                    "size": 999
                }
            }
        }
        """
        )

    DummyBinary._initialize_()
    dummy_bin = DummyBinary.create(
        PyNgOptionsReader(
            buildroot=tmp_path,
            flags={},
            env={},
            configs=[],
        )
    )
    download_req = dummy_bin.get_download_request()

    assert download_req.exe == "dummy_exe"
    assert download_req.download_file_request.expected_digest == FileDigest(
        "d9117a92856a41369888e8d8e823de3dceb86d7bb31f50c38fc1524bf409a308", 12345
    )
    assert download_req.download_file_request.url == "dummy_url1"

    dummy_bin = DummyBinary.create(
        PyNgOptionsReader(
            buildroot=tmp_path,
            flags={"dummy": {"version": ("0.0.2",)}},
            env={},
            configs=[],
        )
    )
    download_req = dummy_bin.get_download_request()

    assert download_req.exe == "dummy_exe"
    assert download_req.download_file_request.expected_digest == FileDigest(
        "ae79f70c751f957b1ce1d619a180953ae8900f4031fd0b7a1c239a5416bc58af", 999
    )
    assert download_req.download_file_request.url == "dummy_url2"
