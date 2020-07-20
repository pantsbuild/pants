# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from uuid import UUID

from pants.engine.internals.uuid import UUIDRequest
from pants.engine.internals.uuid import rules as uuid_rules
from pants.engine.rules import RootRule
from pants.testutil.test_base import TestBase


class UUIDTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *uuid_rules(),
            RootRule(UUIDRequest),
        )

    def test_distinct_uuids(self):
        uuid1 = self.request_single_product(UUID, UUIDRequest())
        uuid2 = self.request_single_product(UUID, UUIDRequest())
        assert uuid1 != uuid2

    def test_identical_uuids(self):
        uuid1 = self.request_single_product(UUID, UUIDRequest(randomizer=0.0))
        uuid2 = self.request_single_product(UUID, UUIDRequest(randomizer=0.0))
        assert uuid1 == uuid2
