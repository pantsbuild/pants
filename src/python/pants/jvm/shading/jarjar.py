# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum, unique

from pants.core.goals.resolves import ExportableTool
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule
from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import BoolOption, EnumOption


@unique
class MisplacedClassStrategy(Enum):
    FATAL = "fatal"
    SKIP = "skip"
    OMIT = "omit"
    MOVE = "move"


class JarJar(JvmToolBase):
    options_scope = "jarjar"
    help = "The Jar Jar Abrams tool (https://github.com/eed3si9n/jarjar-abrams)"

    default_version = "1.8.1"
    default_artifacts = ("com.eed3si9n.jarjar:jarjar-assembly:{version}",)
    default_lockfile_resource = (
        "pants.jvm.shading",
        "jarjar.default.lockfile.txt",
    )

    skip_manifest = BoolOption(default=False, help="Skip the processing of the JAR manifest.")
    misplaced_class_strategy = EnumOption(
        default=None,
        enum_type=MisplacedClassStrategy,
        help="The strategy to use when processing class files that are in the wrong package.",
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(ExportableTool, JarJar),
    ]
