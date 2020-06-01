# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

from pants.backend.python.register import build_file_aliases as register_python
from pants.backend.python.targets.python_binary import PythonBinary
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.resources import Resources
from pants.testutil.subsystem.util import init_subsystem
from pants.testutil.task_test_base import TaskTestBase


class PythonTaskTestBase(TaskTestBase):
    """
    :API: public
    """

    @classmethod
    def alias_groups(cls):
        """
        :API: public
        """
        return register_python().merge(BuildFileAliases(targets={"resources": Resources}))

    def setUp(self):
        super().setUp()
        init_subsystem(PythonBinary.Defaults)

    def create_python_library(
        self, relpath, name, source_contents_map=None, dependencies=(), provides=None
    ):
        """
        :API: public
        """
        sources = (
            []
            if source_contents_map is None
            else ["__init__.py"] + list(source_contents_map.keys())
        )
        sources_strs = [f"'{s}'" for s in sources]
        self.add_to_build_file(
            relpath=relpath,
            target=dedent(
                """
                python_library(
                  name='{name}',
                  {sources_clause}
                  dependencies=[
                    {dependencies}
                  ],
                  {provides_clause}
                )
                """
            ).format(
                name=name,
                sources_clause=f"sources=[{','.join(sources_strs)}],",
                dependencies=",".join(map(repr, dependencies)),
                provides_clause=f"provides={provides}," if provides else "",
            ),
        )
        if source_contents_map:
            self.create_file(relpath=os.path.join(relpath, "__init__.py"))
            for source, contents in source_contents_map.items():
                self.create_file(relpath=os.path.join(relpath, source), contents=contents)
        return self.target(Address(relpath, name).spec)

    def create_python_binary(
        self, relpath, name, entry_point, dependencies=(), provides=None, shebang=None
    ):
        """
        :API: public
        """
        self.add_to_build_file(
            relpath=relpath,
            target=dedent(
                """
                python_binary(
                  name='{name}',
                  entry_point='{entry_point}',
                  dependencies=[
                    {dependencies}
                  ],
                  {provides_clause}
                  {shebang_clause}
                )
                """
            ).format(
                name=name,
                entry_point=entry_point,
                dependencies=",".join(map(repr, dependencies)),
                provides_clause=f"provides={provides}," if provides else "",
                shebang_clause=f"shebang={shebang!r}," if shebang else "",
            ),
        )
        return self.target(Address(relpath, name).spec)

    def create_python_requirement_library(self, relpath, name, requirements):
        """
        :API: public
        """

        def make_requirement(req):
            return f'python_requirement("{req}")'

        self.add_to_build_file(
            relpath=relpath,
            target=dedent(
                """
                python_requirement_library(
                  name='{name}',
                  requirements=[
                    {requirements}
                  ]
                )
                """
            ).format(name=name, requirements=",".join(map(make_requirement, requirements))),
        )
        return self.target(Address(relpath, name).spec)
