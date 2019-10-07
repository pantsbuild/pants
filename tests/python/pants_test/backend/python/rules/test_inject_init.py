# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.inject_init import InjectedInitDigest, inject_init
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, EMPTY_SNAPSHOT, Snapshot
from pants.engine.rules import RootRule
from pants.util.collections import assert_single_element
from pants_test.test_base import TestBase


class TestInjectInit(TestBase):
    @classmethod
    def rules(cls):
        return super().rules() + [inject_init, RootRule(Snapshot)]

    def assert_result(self, input_snapshot, expected_digest):
        injected_digest = assert_single_element(
            self.scheduler.product_request(InjectedInitDigest, [input_snapshot])
        )
        self.assertEqual(injected_digest.directory_digest, expected_digest)

    def test_noops_when_empty_snapshot(self):
        self.assert_result(input_snapshot=EMPTY_SNAPSHOT, expected_digest=EMPTY_DIRECTORY_DIGEST)

    def test_noops_when_init_already_present(self):
        snapshot = self.make_snapshot({"test/foo.py": "", "test/__init__.py": ""})
        self.assert_result(input_snapshot=snapshot, expected_digest=EMPTY_DIRECTORY_DIGEST)

    def test_adds_when_init_missing(self):
        snapshot = self.make_snapshot({"test/foo.py": ""})
        expected_digest = self.make_snapshot({"test/__init__.py": ""}).directory_digest
        self.assert_result(input_snapshot=snapshot, expected_digest=expected_digest)
