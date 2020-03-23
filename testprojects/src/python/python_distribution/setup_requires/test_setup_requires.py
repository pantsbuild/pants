# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from checksum import checksum


# TODO: validate the checksum's value itself?
def test_dist_version():
    assert checksum is not None
    assert isinstance(checksum, str)
    assert len(checksum) == 64
