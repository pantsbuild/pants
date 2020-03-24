# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict
from dataclasses import dataclass
from itertools import zip_longest

from pants.reporting.reporter import Reporter


class JsonReporter(Reporter):
    """A reporter to capture workunit data into a JSON-serializable structure."""

    _log_level_str = [
        "FATAL",
        "ERROR",
        "WARN",
        "INFO",
        "DEBUG",
    ]

    @dataclass(frozen=True)
    class Settings(Reporter.Settings):
        pass

    def __init__(self, run_tracker, settings):
        super().__init__(run_tracker, settings)

        # We accumulate build state into this dict.
        self.results = {}

        # We use a stack to track the nested workunit traversal of each root.
        self._root_id_to_workunit_stack = defaultdict(list)

    def start_workunit(self, workunit):
        """Implementation of Reporter callback."""

        workunit_data = {
            "name": workunit.name,
            "id": str(workunit.id),
            "parent_name": workunit.parent.name if workunit.parent else "",
            "parent_id": str(workunit.parent.id) if workunit.parent else "",
            "labels": list(workunit.labels),
            "cmd": workunit.cmd or "",
            "start_time": workunit.start_time,
            "outputs": defaultdict(str),
            "children": [],
            "log_entries": [],
        }

        root_id = str(workunit.root().id)

        if root_id not in self._root_id_to_workunit_stack:
            self._root_id_to_workunit_stack[root_id].append(workunit_data)
            self.results[root_id] = workunit_data
        else:
            self._root_id_to_workunit_stack[root_id][-1]["children"].append(workunit_data)
            self._root_id_to_workunit_stack[root_id].append(workunit_data)

    def end_workunit(self, workunit):
        """Implementation of Reporter callback."""

        additional_data = {
            "outcome": workunit.outcome_string(workunit.outcome()),
            "end_time": workunit.end_time,
            "unaccounted_time": workunit.unaccounted_time(),
        }

        root_id = str(workunit.root().id)

        # We update the last workunit in the stack, which is always the
        # youngest workunit currently open, and then pop it off. The
        # last workunit serves as a pointer to the child workunit under
        # it's parent (the parent of the youngest workunit currently
        # open is always the one immediately above it in the stack).
        self._root_id_to_workunit_stack[root_id][-1].update(additional_data)
        self._root_id_to_workunit_stack[root_id].pop()

    def handle_output(self, workunit, label, stream):
        """Implementation of Reporter callback."""

        self._root_id_to_workunit_stack[str(workunit.root().id)][-1]["outputs"][label] += stream

    def do_handle_log(self, workunit, level, *msg_elements):
        """Implementation of Reporter callback."""

        entry_info = {
            "level": self._log_level_str[level],
            "messages": self._render_messages(*msg_elements),
        }

        root_id = str(workunit.root().id)
        current_stack = self._root_id_to_workunit_stack[root_id]
        if current_stack:
            current_stack[-1]["log_entries"].append(entry_info)
        else:
            self.results[root_id]["log_entries"].append(entry_info)

    def _render_messages(self, *msg_elements):
        def _message_details(element):
            if isinstance(element, str):
                element = [element]

            text, detail = (x or y for x, y in zip_longest(element, ("", None)))
            return {"text": text, "detail": detail}

        return list(map(_message_details, msg_elements))
