# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar

from pants.bsp.spec.base import StatusCode, TaskId
from pants.bsp.spec.compile import CompileReport, CompileTask


class BSPNotification:
    """Base class for all notifications so that a notification carries its RPC method name."""

    notification_name: ClassVar[str]

    def to_json_dict(self) -> dict[str, Any]:
        raise NotImplementedError


# -----------------------------------------------------------------------------------------------
# Task Notifications
# See https://build-server-protocol.github.io/docs/specification.html#compile-request
# -----------------------------------------------------------------------------------------------


class TaskDataKind(Enum):
    # `data` field must contain a CompileTask object.
    COMPILE_TASK = "compile-task"

    #  `data` field must contain a CompileReport object.
    COMPILE_REPORT = "compile-report"

    # `data` field must contain a TestTask object.
    TEST_TASK = "test-task"

    # `data` field must contain a TestReport object.
    TEST_REPORT = "test-report"

    # `data` field must contain a TestStart object.
    TEST_START = "test-start"

    # `data` field must contain a TestFinish object.
    TEST_FINISH = "test-finish"


@dataclass(frozen=True)
class TaskStartParams(BSPNotification):
    notification_name = "build/taskStart"

    # Unique id of the task with optional reference to parent task id
    task_id: TaskId

    # Timestamp of when the event started in milliseconds since Epoch.
    event_time: int | None = None

    # Message describing the task.
    message: str | None = None

    # Task-specific data.
    # Note: This field is serialized as two fields: `dataKind` (for type name) and `data`.
    data: CompileTask | None = None

    def to_json_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"taskId": self.task_id.to_json_dict()}
        if self.event_time is not None:
            result["eventTime"] = self.event_time
        if self.message is not None:
            result["message"] = self.message
        if self.data is not None:
            if isinstance(self.data, CompileTask):
                result["dataKind"] = TaskDataKind.COMPILE_TASK.value
            else:
                raise AssertionError(
                    f"TaskStartParams contained an unexpected instance: {self.data}"
                )
            result["data"] = self.data.to_json_dict()
        return result


@dataclass(frozen=True)
class TaskProgressParams(BSPNotification):
    notification_name = "build/taskProgress"

    # Unique id of the task with optional reference to parent task id
    task_id: TaskId

    # Timestamp of when the progress event was generated in milliseconds since Epoch.
    event_time: int | None = None

    # Message describing the task progress.
    # Information about the state of the task at the time the event is sent.
    message: str | None = None

    # If known, total amount of work units in this task.
    total: int | None = None

    # If known, completed amount of work units in this task.
    progress: int | None = None

    # Name of a work unit. For example, "files" or "tests". May be empty.
    unit: str | None = None

    # TODO: `data` field is not currently represented. Once we know what types will be sent, then it can be bound.

    def to_json_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"taskId": self.task_id.to_json_dict()}
        if self.event_time is not None:
            result["eventTime"] = self.event_time
        if self.message is not None:
            result["message"] = self.message
        if self.total is not None:
            result["total"] = self.total
        if self.progress is not None:
            result["progress"] = self.progress
        if self.unit is not None:
            result["unit"] = self.unit
        return result


@dataclass(frozen=True)
class TaskFinishParams(BSPNotification):
    notification_name = "build/taskFinish"

    # Unique id of the task with optional reference to parent task id
    task_id: TaskId

    # Timestamp of the event in milliseconds.
    event_time: int | None = None

    # Message describing the finish event.
    message: str | None = None

    # Task completion status.
    status: StatusCode = StatusCode.OK

    # Task-specific data.
    # Note: This field is serialized as two fields: `dataKind` (for type name) and `data`.
    data: CompileReport | None = None

    def to_json_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "taskId": self.task_id.to_json_dict(),
            "status": self.status.value,
        }
        if self.event_time is not None:
            result["eventTime"] = self.event_time
        if self.message is not None:
            result["message"] = self.message
        if self.data is not None:
            if isinstance(self.data, CompileReport):
                result["dataKind"] = TaskDataKind.COMPILE_REPORT.value
            else:
                raise AssertionError(
                    f"TaskFinishParams contained an unexpected instance: {self.data}"
                )
            result["data"] = self.data.to_json_dict()
        return result
