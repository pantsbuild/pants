# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import ExcludesField, JarsField, PrimitiveField
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.java.jar.jar_dependency import JarDependency


class JarLibrary(Target):
    """A set of external JAR files.

    :API: public
    """

    def __init__(self, payload=None, jars=None, managed_dependencies=None, **kwargs):
        """
        :param jars: List of `jar <#jar>`_\\s to depend upon.
        :param managed_dependencies: Address of a managed_jar_dependencies() target to use. If omitted, uses
          the default managed_jar_dependencies() target set by --jar-dependency-management-default-target.
        """
        jars = self.assert_list(jars, expected_type=JarDependency, key_arg="jars")
        payload = payload or Payload()
        payload.add_fields(
            {
                "jars": JarsField(jars),
                "excludes": ExcludesField([]),
                "managed_dependencies": PrimitiveField(managed_dependencies),
            }
        )
        super().__init__(payload=payload, **kwargs)
        # NB: Waiting to validate until superclasses are initialized.
        if not jars:
            raise TargetDefinitionException(self, "Must have a non-empty list of jars.")

    @property
    def managed_dependencies(self):
        """The managed_jar_dependencies target this jar_library specifies, or None.

        :API: public
        """
        if self.payload.managed_dependencies:
            address = Address.parse(
                self.payload.managed_dependencies, relative_to=self.address.spec_path
            )
            self._build_graph.inject_address_closure(address)
            return self._build_graph.get_target(address)
        return None

    @property
    def jar_dependencies(self):
        """
        :API: public
        """
        return self.payload.jars

    @property
    def excludes(self):
        """
        :API: public
        """
        return self.payload.excludes

    @property
    def export_specs(self):
        # Is currently aliased to dependencies. For future work see
        # https://github.com/pantsbuild/pants/issues/4398
        return self.dependencies

    @property
    def strict_deps(self):
        return False
