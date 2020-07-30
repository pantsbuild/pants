# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.option.subsystem import Subsystem


class Subprocess:
    class Factory(Subsystem):
        """A subsystem for managing subprocess state."""

        # N.B. This scope is completely unused as of now, as this subsystem's current primary function
        # is to surface the `--pants-subprocessdir` global/bootstrap option at runtime. This option
        # needs to be set on the bootstrap scope vs a Subsystem scope such that we have early access
        # to the option (e.g. via `OptionsBootstrapper` vs `OptionsInitializer`) in order to bootstrap
        # process-metadata dependent runs such as the pantsd thin client runner (`RemotePantsRunner`).
        options_scope = "subprocess"

        def create(self):
            return Subprocess(self.global_instance().options.pants_subprocessdir)

    def __init__(self, pants_subprocess_dir):
        self._pants_subprocess_dir = pants_subprocess_dir

    def get_subprocess_dir(self):
        return self._pants_subprocess_dir
