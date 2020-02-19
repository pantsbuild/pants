# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.app_base import AppBase


class JvmApp(AppBase):
    """A deployable JVM application.

    Invoking the ``bundle`` goal on one of these targets creates a
    self-contained artifact suitable for deployment on some other machine.
    The artifact contains the executable jar, its dependencies, and
    extra files like config files, startup scripts, etc.

    :API: public
    """

    def __init__(self, payload=None, deployjar=None, **kwargs):
        """
        :param boolean deployjar: If True, pack all 3rdparty and internal jar classfiles into
          a single deployjar in the bundle's root dir. If unset, all jars will go into the
          bundle's libs directory, the root will only contain a synthetic jar with its manifest's
          Class-Path set to those jars.
        """
        payload = payload or Payload()
        payload.add_field("deployjar", PrimitiveField(deployjar))
        super().__init__(payload=payload, **kwargs)

    @classmethod
    def binary_target_type(cls):
        return JvmBinary

    @property
    def basename(self):
        return self.payload.basename

    @property
    def jar_dependencies(self):
        return self.binary.jar_dependencies
