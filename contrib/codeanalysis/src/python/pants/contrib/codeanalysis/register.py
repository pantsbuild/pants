# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.codeanalysis.tasks.bundle_entries import BundleEntries
from pants.contrib.codeanalysis.tasks.extract_java import ExtractJava
from pants.contrib.codeanalysis.tasks.index_java import IndexJava


def register_goals():
  task(name='kythe-java-extract', action=ExtractJava).install('index')
  task(name='kythe-java-index', action=IndexJava).install('index')
  task(name='bundle-entries', action=BundleEntries).install('index')
