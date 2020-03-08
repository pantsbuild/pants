# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import threading
from io import BytesIO
from queue import Empty, Queue

from pants.task.console_task import ConsoleTask
from pants.testutil.task_test_base import TaskTestBase


class ConsoleTaskTest(TaskTestBase):
    class Infinite(ConsoleTask):
        def __init__(self, *args, **kwargs):
            super(ConsoleTaskTest.Infinite, self).__init__(*args, **kwargs)
            self.halt = threading.Event()

        def console_output(self, _):
            while not self.halt.isSet():
                yield "jake"

        def stop(self):
            self.halt.set()

    @classmethod
    def task_type(cls):
        return cls.Infinite

    class PrintTargets(ConsoleTask):
        options_scope = "print-targets"

        def console_output(self, targets):
            for tgt in targets:
                yield tgt.address.spec

    def test_transitivity(self):
        a = self.make_target("src:a")
        b = self.make_target("src:b", dependencies=[a])

        s = BytesIO()
        self.set_options_for_scope("print-targets", transitive=True)
        task_transitive = self.PrintTargets(
            self.context(for_task_types=[self.PrintTargets], console_outstream=s, target_roots=[b]),
            self.test_workdir,
        )
        task_transitive.execute()
        self.assertEqual(s.getvalue().decode(), "src:b\nsrc:a\n")

        s = BytesIO()
        self.set_options_for_scope("print-targets", transitive=False)
        task_intransitive = self.PrintTargets(
            self.context(for_task_types=[self.PrintTargets], console_outstream=s, target_roots=[b]),
            self.test_workdir,
        )
        task_intransitive.execute()
        self.assertEqual(s.getvalue().decode(), "src:b\n")

    def test_sigpipe(self):
        r, w = os.pipe()
        outstream = os.fdopen(w, "wb")
        task = self.create_task(self.context(console_outstream=outstream))
        raised = Queue(maxsize=1)

        def execute():
            try:
                task.execute()
            except IOError as e:
                raised.put(e)

        execution = threading.Thread(target=execute, name="ConsoleTaskTestBase_sigpipe")
        execution.setDaemon(True)
        execution.start()
        try:
            data = os.read(r, 5)
            self.assertEqual(b"jake\n", data)
            os.close(r)
        finally:
            task.stop()
            execution.join()

        with self.assertRaises(Empty):
            e = raised.get_nowait()

            # Instead of taking the generic assertRaises raises message, provide a more detailed failure
            # message that shows exactly what untrapped error was on the queue.
            self.fail(f"task raised {e}")
