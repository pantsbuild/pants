# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations


from pants.engine.internals import native_engine


def foo() -> None:
    native_parser = native_engine.PyOptionParser([], {}, None, True, False)
    option_id = native_engine.PyOptionId("version_for_resolve", scope="scala")
    val = native_parser.get_dict(option_id, {"FOO": "BAR", "BAZ": 55, "QUX": True, "QUUX": 5.4, "FIZZ": [1, 2], "BUZZ": {"X": "Y"}})
    print(f"XXXXXX {val}")
