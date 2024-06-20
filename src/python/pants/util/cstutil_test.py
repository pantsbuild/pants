# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import libcst as cst
import libcst.matchers as m

from pants.util import cstutil


def test_make_importfrom():
    imp = cstutil.make_importfrom("pants.engine.rules", "collect_rules")
    assert imp.deep_equals(
        cst.ImportFrom(
            module=cst.Attribute(
                value=cst.Attribute(
                    value=cst.Name("pants"),
                    attr=cst.Name("engine"),
                ),
                attr=cst.Name("rules"),
            ),
            names=[cst.ImportAlias(name=cst.Name("collect_rules"))],
        )
    )


def test_make_importfrom_attr():
    attr = cstutil.make_importfrom_attr("pants.engine.rules")
    assert attr.deep_equals(
        cst.Attribute(
            value=cst.Attribute(
                value=cst.Name("pants"),
                attr=cst.Name("engine"),
            ),
            attr=cst.Name("rules"),
        )
    )


def test_make_importfrom_attr_matcher():
    node = cstutil.make_importfrom_attr("pants.engine.rules")
    assert m.matches(node, cstutil.make_importfrom_attr_matcher("pants.engine.rules"))
    assert not m.matches(node, cstutil.make_importfrom_attr_matcher("pants.engine.rulez"))
