# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.fs import Digest, Snapshot
from pants.source.payload_fields import SourcesField
from pants.source.wrapped_globs import Globs, LazyFilesetWithSpec
from pants.testutil.test_base import TestBase


class PayloadTest(TestBase):
    def sources(self, rel_path: str, *args) -> LazyFilesetWithSpec:
        return Globs.create_fileset_with_spec(rel_path, *args)

    def test_sources_field(self) -> None:
        self.create_file("foo/bar/a.txt", "a_contents")
        self.create_file("foo/bar/b.txt", "b_contents")

        self.assertNotEqual(
            SourcesField(sources=self.sources("foo/bar", "a.txt"),).fingerprint(),
            SourcesField(sources=self.sources("foo/bar", "b.txt"),).fingerprint(),
        )

        self.assertEqual(
            SourcesField(sources=self.sources("foo/bar", "a.txt"),).fingerprint(),
            SourcesField(sources=self.sources("foo/bar", "a.txt"),).fingerprint(),
        )

        self.assertEqual(
            SourcesField(sources=self.sources("foo/bar", "a.txt", "b.txt"),).fingerprint(),
            SourcesField(sources=self.sources("foo/bar", "a.txt", "b.txt"),).fingerprint(),
        )

        fp1 = SourcesField(sources=self.sources("foo/bar", "a.txt"),).fingerprint()
        self.create_file("foo/bar/a.txt", "a_contents_different")
        fp2 = SourcesField(sources=self.sources("foo/bar", "a.txt"),).fingerprint()

        self.assertNotEqual(fp1, fp2)

    def test_fails_on_invalid_sources_kwarg(self) -> None:
        with self.assertRaises(ValueError):
            SourcesField(sources="not-a-list")  # type: ignore[arg-type]

    def test_passes_lazy_fileset_with_spec_through(self) -> None:
        self.create_file("foo/a.txt", "a_contents")

        fileset = LazyFilesetWithSpec("foo", {"globs": ["foo/a.txt"]}, lambda: ["foo/a.txt"])
        sf = SourcesField(sources=fileset)

        self.assertIs(fileset, sf.sources)
        self.assertEqual(["foo/a.txt"], list(sf.source_paths))

    def test_passes_eager_fileset_with_spec_through(self) -> None:
        self.create_file("foo/foo/a.txt", "a_contents")

        fileset = self.sources_for(["foo/a.txt"], "foo")

        sf = SourcesField(sources=fileset)

        self.assertIs(fileset, sf.sources)
        self.assertEqual(["foo/a.txt"], list(sf.source_paths))
        self.assertEqual(["foo/foo/a.txt"], list(sf.relative_to_buildroot()))

        digest = "56001a7e48555f156420099a99da60a7a83acc90853046709341bf9f00a6f944"
        want_snapshot = Snapshot(Digest(digest, 77), ("foo/foo/a.txt",), ())

        # We explicitly pass a None scheduler because we expect no scheduler lookups to be required
        # in order to get a Snapshot.
        self.assertEqual(sf.snapshot(scheduler=None), want_snapshot)
