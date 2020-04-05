# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Various goals for insights on your project's graph, such as finding the path between any two
targets."""

from pants.backend.graph_info.tasks.cloc import CountLinesOfCode
from pants.backend.graph_info.tasks.dependees import ReverseDepmap
from pants.backend.graph_info.tasks.filemap import Filemap
from pants.backend.graph_info.tasks.filter import Filter
from pants.backend.graph_info.tasks.minimal_cover import MinimalCover
from pants.backend.graph_info.tasks.paths import Path, Paths
from pants.backend.graph_info.tasks.sort_targets import SortTargets
from pants.goal.task_registrar import TaskRegistrar as task


def register_goals():
    task(name="path", action=Path).install()
    task(name="paths", action=Paths).install()
    task(name="dependees", action=ReverseDepmap).install()
    task(name="filemap", action=Filemap).install()
    task(name="minimize", action=MinimalCover).install()
    task(name="filter", action=Filter).install()
    task(name="sort", action=SortTargets).install()
    task(name="cloc", action=CountLinesOfCode).install()
