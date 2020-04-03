# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.scoverage_platform import ScoveragePlatform
from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.address import Address
from pants.build_graph.target import Target

SCOVERAGE = "scoverage"


class ScalaLibrary(ExportableJvmLibrary):
    """A Scala library.

    Normally has conceptually-related sources; invoking the ``compile`` goal
    on this target compiles scala and generates classes. Invoking the ``bundle``
    goal on this target creates a ``.jar``; but that's an unusual thing to do.
    Instead, a ``jvm_binary`` might depend on this library; that binary is a
    more sensible thing to bundle.

    :API: public
    """

    default_sources_globs = "*.scala"
    default_sources_exclude_globs = JUnitTests.scala_test_globs

    @classmethod
    def subsystems(cls):
        return super().subsystems() + (ScalaPlatform, ScoveragePlatform,)

    @staticmethod
    def skip_instrumentation(**kwargs):
        return Target.compute_target_id(kwargs["address"]).startswith(
            ".pants.d.gen"
        ) or ScoveragePlatform.global_instance().is_blacklisted(kwargs["address"].spec)

    def __init__(
        self,
        java_sources=None,
        scalac_plugins=None,
        scalac_plugin_args=None,
        compiler_option_sets=None,
        payload=None,
        **kwargs,
    ):
        """
        :param java_sources: Java libraries this library has a *circular*
          dependency on.
          If you don't have the particular problem of circular dependencies
          forced by splitting interdependent java and scala into multiple targets,
          don't use this at all.
          Prefer using ``dependencies`` to express non-circular dependencies.
        :type java_sources: address spec or list of address specs
        """
        payload = payload or Payload()
        payload.add_fields(
            {
                "java_sources": PrimitiveField(
                    self.assert_list(java_sources, key_arg="java_sources")
                ),
            }
        )

        scalac_plugins = scalac_plugins or []
        scalac_plugin_args = scalac_plugin_args or {}
        # Allow lists as well as sets in BUILD files:
        compiler_option_sets = set(compiler_option_sets) if compiler_option_sets else set()

        # Modify these options in case scoverage is enabled.
        if ScoveragePlatform.global_instance().get_options().enable_scoverage:
            if not self.skip_instrumentation(**kwargs):
                scalac_plugins.append(SCOVERAGE)

                scalac_plugin_args.update(
                    {
                        "scoverage": [
                            "writeToClasspath:true",
                            f"dataDir:{Target.compute_target_id(kwargs['address'])}",
                        ]
                    }
                )

                compiler_option_sets.update([SCOVERAGE])

        super().__init__(
            payload=payload,
            scalac_plugins=scalac_plugins,
            scalac_plugin_args=scalac_plugin_args,
            compiler_option_sets=compiler_option_sets,
            **kwargs,
        )

    @classmethod
    def compute_injectable_address_specs(cls, kwargs=None, payload=None):
        for address_spec in super().compute_injectable_address_specs(kwargs, payload):
            yield address_spec

        target_representation = kwargs or payload.as_dict()
        java_sources_specs = target_representation.get("java_sources", None) or []
        for java_source_spec in java_sources_specs:
            yield java_source_spec

    @classmethod
    def compute_dependency_address_specs(cls, kwargs=None, payload=None):
        for address_spec in super().compute_dependency_address_specs(kwargs, payload):
            yield address_spec

        for address_spec in ScalaPlatform.global_instance().injectables_address_specs_for_key(
            "scala-library"
        ):
            yield address_spec

        if ScoveragePlatform.global_instance().get_options().enable_scoverage:
            for (
                address_spec
            ) in ScoveragePlatform.global_instance().injectables_address_specs_for_key("scoverage"):
                yield address_spec

    def get_jar_dependencies(self):
        for jar in super().get_jar_dependencies():
            yield jar
        for java_source_target in self.java_sources:
            for jar in java_source_target.jar_dependencies:
                yield jar

    @property
    def java_sources(self):
        targets = []
        for spec in self.payload.java_sources:
            address = Address.parse(spec, relative_to=self.address.spec_path)
            target = self._build_graph.get_target(address)
            if target is None:
                raise TargetDefinitionException(self, f"No such java target: {spec}")
            targets.append(target)
        return targets
