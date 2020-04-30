# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import tarfile
import zipfile
from io import BytesIO

from pants.core.util_rules.archive import ExtractedDigest, MaybeExtractable
from pants.core.util_rules.archive import rules as archive_rules
from pants.engine.fs import FileContent, FilesContent, Snapshot
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.testutil.test_base import TestBase


class ArchiveTest(TestBase):

    files = {"foo": b"bar", "hello/world": b"Hello, World!"}

    expected_files_content = FilesContent(
        [FileContent(name, content) for name, content in files.items()]
    )

    @classmethod
    def rules(cls):
        return (*super().rules(), *archive_rules(), RootRule(Snapshot))

    # TODO: Figure out a way to run these tests without a TestBase subclass, and use
    #  pytest.mark.parametrize.
    def _do_test_extract_zip(self, compression) -> None:
        io = BytesIO()
        with zipfile.ZipFile(io, "w", compression=compression) as zf:
            for name, content in self.files.items():
                zf.writestr(name, content)
        io.flush()
        input_snapshot = self.make_snapshot({"test.zip": io.getvalue()})
        extracted_digest = self.request_single_product(
            ExtractedDigest, Params(MaybeExtractable(input_snapshot.digest))
        )

        files_content = self.request_single_product(FilesContent, Params(extracted_digest.digest))
        assert self.expected_files_content == files_content

    def test_extract_zip_stored(self) -> None:
        self._do_test_extract_zip(zipfile.ZIP_STORED)

    def test_extract_zip_deflated(self) -> None:
        self._do_test_extract_zip(zipfile.ZIP_DEFLATED)

    # TODO: Figure out a way to run these tests without a TestBase subclass, and use
    #  pytest.mark.parametrize.
    def _do_test_extract_tar(self, compression) -> None:
        io = BytesIO()
        mode = f"w:{compression}" if compression else "w"
        with tarfile.open(mode=mode, fileobj=io) as tf:
            for name, content in self.files.items():
                tarinfo = tarfile.TarInfo(name)
                tarinfo.size = len(content)
                tf.addfile(tarinfo, BytesIO(content))
        ext = f"tar.{compression}" if compression else "tar"
        input_snapshot = self.make_snapshot({f"test.{ext}": io.getvalue()})
        extracted_digest = self.request_single_product(
            ExtractedDigest, Params(MaybeExtractable(input_snapshot.digest))
        )

        files_content = self.request_single_product(FilesContent, Params(extracted_digest.digest))
        assert self.expected_files_content == files_content

    def test_extract_tar(self) -> None:
        self._do_test_extract_tar("")

    def test_extract_tar_gz(self) -> None:
        self._do_test_extract_tar("gz")

    def test_extract_tar_bz2(self) -> None:
        self._do_test_extract_tar("bz2")

    def test_extract_tar_xz(self) -> None:
        self._do_test_extract_tar("xz")

    def test_non_archive(self) -> None:
        input_snapshot = self.make_snapshot({"test.sh": b"# A shell script"})
        extracted_digest = self.request_single_product(
            ExtractedDigest, Params(MaybeExtractable(input_snapshot.digest))
        )

        files_content = self.request_single_product(FilesContent, Params(extracted_digest.digest))
        assert FilesContent([FileContent("test.sh", b"# A shell script")]) == files_content
