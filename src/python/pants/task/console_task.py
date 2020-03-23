# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import os
from contextlib import contextmanager

from pants.base.exceptions import TaskError
from pants.task.task import QuietTaskMixin, Task
from pants.util.dirutil import safe_open
from pants.util.meta import classproperty


class ConsoleTask(QuietTaskMixin, Task):
    """A task whose only job is to print information to the console.

    ConsoleTasks are not intended to modify build state.
    """

    @classproperty
    def _register_console_transitivity_option(cls):
        """Some tasks register their own --transitive option, which act differently."""
        return True

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--sep", default="\\n", metavar="<separator>", help="String to use to separate results."
        )
        register(
            "--output-file", metavar="<path>", help="Write the console output to this file instead."
        )

        if cls._register_console_transitivity_option:
            register(
                "--transitive",
                type=bool,
                default=False,
                fingerprint=True,
                help="If True, use all targets in the build graph, else use only target roots.",
            )

    @property
    def act_transitively(self):
        # `Task` defaults to returning `True` in `act_transitively`, so we keep that default value.
        return self.get_options().get("transitive", True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._console_separator = self.get_options().sep.encode().decode("unicode_escape")
        if self.get_options().output_file:
            try:
                self._outstream = safe_open(os.path.abspath(self.get_options().output_file), "wb")
            except IOError as e:
                raise TaskError(
                    "Error opening stream {out_file} due to"
                    " {error_str}".format(out_file=self.get_options().output_file, error_str=e)
                )
        else:
            self._outstream = self.context.console_outstream

    @contextmanager
    def _guard_sigpipe(self):
        try:
            yield
        except IOError as e:
            # If the pipeline only wants to read so much, that's fine; otherwise, this error is probably
            # legitimate.
            if e.errno != errno.EPIPE:
                raise e

    def execute(self):
        with self._guard_sigpipe():
            try:
                targets = self.get_targets() if self.act_transitively else self.context.target_roots
                for value in self.console_output(targets) or tuple():
                    self._outstream.write(value.encode())
                    self._outstream.write(self._console_separator.encode())
            finally:
                self._outstream.flush()
                if self.get_options().output_file:
                    self._outstream.close()

    def console_output(self, targets):
        raise NotImplementedError("console_output must be implemented by subclasses of ConsoleTask")
