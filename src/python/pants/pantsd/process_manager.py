# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import signal
import sys
import time
import traceback
from abc import ABCMeta
from hashlib import sha256
from typing import Callable, cast

import psutil

from pants.base.build_environment import get_buildroot
from pants.bin.pants_env_vars import DAEMON_ENTRYPOINT
from pants.engine.internals.native_engine import pantsd_fingerprint_compute
from pants.option.options import Options
from pants.option.scope import GLOBAL_SCOPE
from pants.pantsd.lock import OwnerPrintingInterProcessFileLock
from pants.util.dirutil import read_file, rm_rf, safe_file_dump, safe_mkdir
from pants.util.memo import memoized_classproperty, memoized_property

logger = logging.getLogger(__name__)


class ProcessManager:
    """Manages contextual, on-disk process metadata.

    Metadata is stored under a per-host fingerprinted directory, and a nested per-named-process
    directory. The per-host directory defends against attempting to use process metadata that has
    been mounted into virtual machines or docker images.
    """

    class MetadataError(Exception):
        pass

    class Timeout(Exception):
        pass

    class NonResponsiveProcess(Exception):
        pass

    class NotStarted(Exception):
        pass

    KILL_WAIT_SEC = 5
    KILL_CHAIN = (signal.SIGTERM, signal.SIGKILL)

    FAIL_WAIT_SEC = 10
    INFO_INTERVAL_SEC = 5
    WAIT_INTERVAL_SEC = 0.1

    SOCKET_KEY = "socket"
    PROCESS_NAME_KEY = "process_name"
    PID_KEY = "pid"
    FINGERPRINT_KEY = "fingerprint"

    def __init__(self, name: str, metadata_base_dir: str) -> None:
        """
        :param string name: The process identity/name (e.g. 'pantsd' or 'ng_Zinc').
        :param str metadata_base_dir: The overridden base directory for process metadata.
        """
        super().__init__()
        self._metadata_base_dir = metadata_base_dir
        self._name = name.lower().strip()
        # TODO: Extract process spawning code.
        self._buildroot = get_buildroot()

    @memoized_classproperty
    def host_fingerprint(cls) -> str:
        """A fingerprint that attempts to identify the potential scope of a live process.

        See the class pydoc.

        In the absence of kernel hotswapping, a new uname means a restart or virtual machine, both
        of which mean that process metadata is invalid. Additionally, docker generates a random
        hostname per instance, which improves the reliability of this hash.

        TODO: It would be nice to be able to use `uptime` (e.g. https://crates.io/crates/uptime_lib)
        to identify reboots, but it's more challenging than it should be because it would involve
        subtracting from the current time, which might hit aliasing issues.
        """
        hasher = sha256()
        for component in os.uname():
            hasher.update(component.encode())
        return hasher.hexdigest()[:12]

    @staticmethod
    def _maybe_cast(item, caster):
        """Given a casting function, attempt to cast to that type while masking common cast
        exceptions.

        N.B. This is mostly suitable for casting string types to numeric types - e.g. a port number
        read from disk into an int.

        :param func caster: A casting callable (e.g. `int`).
        :returns: The result of caster(item) or item if TypeError or ValueError are raised during cast.
        """
        try:
            return caster(item)
        except (TypeError, ValueError):
            # N.B. the TypeError catch here (already) protects against the case that caster is None.
            return item

    @classmethod
    def _deadline_until(
        cls,
        closure: Callable[[], bool],
        ongoing_msg: str,
        completed_msg: str,
        timeout: float = FAIL_WAIT_SEC,
        wait_interval: float = WAIT_INTERVAL_SEC,
        info_interval: float = INFO_INTERVAL_SEC,
    ):
        """Execute a function/closure repeatedly until a True condition or timeout is met.

        :param func closure: the function/closure to execute (should not block for long periods of time
                             and must return True on success).
        :param str ongoing_msg: a description of the action that is being executed, to be rendered as
                                info while we wait, and as part of any rendered exception.
        :param str completed_msg: a description of the action that is being executed, to be rendered
                                after the action has succeeded (but only if we have previously rendered
                                the ongoing_msg).
        :param float timeout: the maximum amount of time to wait for a true result from the closure in
                              seconds. N.B. this is timing based, so won't be exact if the runtime of
                              the closure exceeds the timeout.
        :param float wait_interval: the amount of time to sleep between closure invocations.
        :param float info_interval: the amount of time to wait before and between reports via info
                                    logging that we're still waiting for the closure to succeed.
        :raises: :class:`ProcessManager.Timeout` on execution timeout.
        """
        now = time.time()
        deadline = now + timeout
        info_deadline = now + info_interval
        rendered_ongoing = False
        while 1:
            if closure():
                if rendered_ongoing:
                    logger.info(completed_msg)
                return True

            now = time.time()
            if now > deadline:
                raise cls.Timeout(
                    "exceeded timeout of {} seconds while waiting for {}".format(
                        timeout, ongoing_msg
                    )
                )

            if now > info_deadline:
                logger.info(f"waiting for {ongoing_msg}...")
                rendered_ongoing = True
                info_deadline = info_deadline + info_interval
            elif wait_interval:
                time.sleep(wait_interval)

    @classmethod
    def _wait_for_file(
        cls,
        filename: str,
        ongoing_msg: str,
        completed_msg: str,
        timeout: float = FAIL_WAIT_SEC,
        want_content: bool = True,
    ):
        """Wait up to timeout seconds for filename to appear with a non-zero size or raise
        Timeout()."""

        def file_waiter():
            return os.path.exists(filename) and (not want_content or os.path.getsize(filename))

        return cls._deadline_until(file_waiter, ongoing_msg, completed_msg, timeout=timeout)

    @classmethod
    def _get_metadata_dir_by_name(cls, name: str, metadata_base_dir: str) -> str:
        """Retrieve the metadata dir by name.

        This should always live outside of the workdir to survive a clean-all.
        """
        return os.path.join(metadata_base_dir, cls.host_fingerprint, name)

    def _metadata_file_path(self, metadata_key) -> str:
        return self.metadata_file_path(self.name, metadata_key, self._metadata_base_dir)

    @classmethod
    def metadata_file_path(cls, name, metadata_key, metadata_base_dir) -> str:
        return os.path.join(cls._get_metadata_dir_by_name(name, metadata_base_dir), metadata_key)

    def read_metadata_by_name(self, metadata_key, caster=None):
        """Read process metadata using a named identity.

        :param string metadata_key: The metadata key (e.g. 'pid').
        :param func caster: A casting callable to apply to the read value (e.g. `int`).
        """
        file_path = self._metadata_file_path(metadata_key)
        try:
            metadata = read_file(file_path).strip()
            return self._maybe_cast(metadata, caster)
        except OSError:
            return None

    def write_metadata_by_name(self, metadata_key, metadata_value) -> None:
        """Write process metadata using a named identity.

        :param string metadata_key: The metadata key (e.g. 'pid').
        :param string metadata_value: The metadata value (e.g. '1729').
        """
        safe_mkdir(self._get_metadata_dir_by_name(self.name, self._metadata_base_dir))
        file_path = self._metadata_file_path(metadata_key)
        safe_file_dump(file_path, metadata_value)

    def await_metadata_by_name(
        self, metadata_key, ongoing_msg: str, completed_msg: str, timeout: float, caster=None
    ):
        """Block up to a timeout for process metadata to arrive on disk.

        :param string metadata_key: The metadata key (e.g. 'pid').
        :param str ongoing_msg: A message that describes what is being waited for while waiting.
        :param str completed_msg: A message that describes what was being waited for after completion.
        :param float timeout: The deadline to write metadata.
        :param type caster: A type-casting callable to apply to the read value (e.g. int, str).
        :returns: The value of the metadata key (read from disk post-write).
        :raises: :class:`ProcessManager.Timeout` on timeout.
        """
        file_path = self._metadata_file_path(metadata_key)
        self._wait_for_file(file_path, ongoing_msg, completed_msg, timeout=timeout)
        return self.read_metadata_by_name(metadata_key, caster)

    def purge_metadata_by_name(self, name) -> None:
        """Purge a processes metadata directory.

        :raises: `ProcessManager.MetadataError` when OSError is encountered on metadata dir removal.
        """
        meta_dir = self._get_metadata_dir_by_name(name, self._metadata_base_dir)
        logger.debug(f"purging metadata directory: {meta_dir}")
        try:
            rm_rf(meta_dir)
        except OSError as e:
            raise ProcessManager.MetadataError(
                f"failed to purge metadata directory {meta_dir}: {e!r}"
            )

    @property
    def name(self):
        """The logical name/label of the process."""
        return self._name

    @memoized_property
    def lifecycle_lock(self):
        """An identity-keyed inter-process lock for safeguarding lifecycle and other operations."""
        safe_mkdir(self._metadata_base_dir)
        return OwnerPrintingInterProcessFileLock(
            # N.B. This lock can't key into the actual named metadata dir (e.g. `.pids/pantsd/lock`
            # via `ProcessManager._get_metadata_dir_by_name()`) because of a need to purge
            # the named metadata dir on startup to avoid stale metadata reads.
            os.path.join(self._metadata_base_dir, f".lock.{self._name}")
        )

    @property
    def fingerprint(self):
        """The fingerprint of the current process.

        This reads the current fingerprint from the `ProcessManager` metadata.

        :returns: The fingerprint of the running process as read from ProcessManager metadata or `None`.
        :rtype: string
        """
        return self.read_metadata_by_name(self.FINGERPRINT_KEY)

    @property
    def pid(self):
        """The running processes pid (or None)."""
        return self.read_metadata_by_name(self.PID_KEY, int)

    @property
    def process_name(self):
        """The process name, to be compared to the psutil exe_name for stale pid checking."""
        return self.read_metadata_by_name(self.PROCESS_NAME_KEY, str)

    @property
    def socket(self):
        """The running processes socket/port information (or None)."""
        return self.read_metadata_by_name(self.SOCKET_KEY, int)

    def has_current_fingerprint(self, fingerprint):
        """Determines if a new fingerprint is the current fingerprint of the running process.

        :param string fingerprint: The new fingerprint to compare to.
        :rtype: bool
        """
        return fingerprint == self.fingerprint

    def needs_restart(self, fingerprint):
        """Determines if the current ProcessManager needs to be started or restarted.

        :param string fingerprint: The new fingerprint to compare to.
        :rtype: bool
        """
        return self.is_dead() or not self.has_current_fingerprint(fingerprint)

    def await_pid(self, timeout: float) -> int:
        """Wait up to a given timeout for a process to write pid metadata."""
        return cast(
            int,
            self.await_metadata_by_name(
                self.PID_KEY,
                f"{self._name} to start",
                f"{self._name} started",
                timeout,
                caster=int,
            ),
        )

    def await_socket(self, timeout: float) -> int:
        """Wait up to a given timeout for a process to write socket info."""
        return cast(
            int,
            self.await_metadata_by_name(
                self.SOCKET_KEY,
                f"{self._name} socket to be opened",
                f"{self._name} socket opened",
                timeout,
                caster=int,
            ),
        )

    def write_pid(self, pid: int | None = None):
        """Write the current process's PID."""
        pid = os.getpid() if pid is None else pid
        self.write_metadata_by_name(self.PID_KEY, str(pid))

    def _get_process_name(self, process: psutil.Process | None = None) -> str:
        proc = process or self._as_process()
        cmdline = proc.cmdline()
        return cast(str, cmdline[0] if cmdline else proc.name())

    def write_process_name(self, process_name: str | None = None):
        """Write the current process's name."""
        process_name = process_name or self._get_process_name()
        self.write_metadata_by_name(self.PROCESS_NAME_KEY, process_name)

    def write_socket(self, socket_info: int):
        """Write the local processes socket information (TCP port or UNIX socket)."""
        self.write_metadata_by_name(self.SOCKET_KEY, str(socket_info))

    def write_fingerprint(self, fingerprint: str) -> None:
        self.write_metadata_by_name(self.FINGERPRINT_KEY, fingerprint)

    def _as_process(self):
        """Returns a psutil `Process` object wrapping our pid.

        NB: Even with a process object in hand, subsequent method calls against it can always raise
        `NoSuchProcess`.  Care is needed to document the raises in the public API or else trap them and
        do something sensible for the API.

        :returns: a psutil Process object or else None if we have no pid.
        :rtype: :class:`psutil.Process`
        :raises: :class:`psutil.NoSuchProcess` if the process identified by our pid has died.
        :raises: :class:`self.NotStarted` if no pid has been recorded for this process.
        """
        pid = self.pid
        if not pid:
            raise self.NotStarted()
        return psutil.Process(pid)

    def is_dead(self):
        """Return a boolean indicating whether the process is dead or not."""
        return not self.is_alive()

    def is_alive(self, extended_check=None):
        """Return a boolean indicating whether the process is running or not.

        :param func extended_check: An additional callable that will be invoked to perform an extended
                                    liveness check. This callable should take a single argument of a
                                    `psutil.Process` instance representing the context-local process
                                    and return a boolean True/False to indicate alive vs not alive.
        """
        try:
            process = self._as_process()
            return not (
                # Can happen if we don't find our pid.
                (not process)
                or
                # Check for walkers.
                (process.status() == psutil.STATUS_ZOMBIE)
                or
                # Check for stale pids.
                (self.process_name and self.process_name != self._get_process_name(process))
                or
                # Extended checking.
                (extended_check and not extended_check(process))
            )
        except (self.NotStarted, psutil.NoSuchProcess, psutil.AccessDenied):
            # On some platforms, accessing attributes of a zombie'd Process results in NoSuchProcess.
            return False

    def purge_metadata(self, force=False):
        """Instance-based version of ProcessManager.purge_metadata_by_name() that checks for process
        liveness before purging metadata.

        :param bool force: If True, skip process liveness check before purging metadata.
        :raises: `ProcessManager.MetadataError` when OSError is encountered on metadata dir removal.
        """
        if not force and self.is_alive():
            raise ProcessManager.MetadataError("cannot purge metadata for a running process!")

        self.purge_metadata_by_name(self._name)

    def _kill(self, kill_sig):
        """Send a signal to the current process."""
        if self.pid:
            os.kill(self.pid, kill_sig)

    def terminate(self, signal_chain=KILL_CHAIN, kill_wait=KILL_WAIT_SEC, purge=True):
        """Ensure a process is terminated by sending a chain of kill signals (SIGTERM, SIGKILL)."""
        alive = self.is_alive()
        if alive:
            logger.debug(f"terminating {self._name}")
            for signal_type in signal_chain:
                pid = self.pid
                try:
                    logger.debug(f"sending signal {signal_type} to pid {pid}")
                    self._kill(signal_type)
                except OSError as e:
                    logger.warning(
                        "caught OSError({e!s}) during attempt to kill -{signal} {pid}!".format(
                            e=e, signal=signal_type, pid=pid
                        )
                    )

                # Wait up to kill_wait seconds to terminate or move onto the next signal.
                try:
                    if self._deadline_until(
                        self.is_dead,
                        f"{self._name} to exit",
                        f"{self._name} exited",
                        timeout=kill_wait,
                    ):
                        alive = False
                        logger.debug(f"successfully terminated pid {pid}")
                        break
                except self.Timeout:
                    # Loop to the next kill signal on timeout.
                    pass

        if alive:
            raise ProcessManager.NonResponsiveProcess(
                "failed to kill pid {pid} with signals {chain}".format(
                    pid=self.pid, chain=signal_chain
                )
            )

        if purge:
            self.purge_metadata(force=True)

    def daemon_spawn(
        self, pre_fork_opts=None, post_fork_parent_opts=None, post_fork_child_opts=None
    ):
        """Perform a single-fork to run a subprocess and write the child pid file.

        Use this if your post_fork_child block invokes a subprocess via subprocess.Popen(). In this
        case, a second fork is extraneous given that Popen() also forks. Using this daemonization
        method leaves the responsibility of writing the pid to the caller to allow for library-
        agnostic flexibility in subprocess execution.
        """
        self.purge_metadata()
        self.pre_fork(**pre_fork_opts or {})
        pid = os.fork()
        if pid == 0:
            # fork's child execution
            try:
                os.setsid()
                os.chdir(self._buildroot)
                self.post_fork_child(**post_fork_child_opts or {})
            except Exception:
                logger.critical(traceback.format_exc())
            finally:
                os._exit(0)
        else:
            # fork's parent execution
            try:
                self.post_fork_parent(**post_fork_parent_opts or {})
            except Exception:
                logger.critical(traceback.format_exc())

    def pre_fork(self):
        """Pre-fork callback for subclasses."""

    def post_fork_child(self):
        """Pre-fork child callback for subclasses."""

    def post_fork_parent(self):
        """Post-fork parent callback for subclasses."""


class PantsDaemonProcessManager(ProcessManager, metaclass=ABCMeta):
    """An ABC for classes that interact with pantsd's metadata.

    This is extended by both a pantsd client handle, and by the server: the client reads process
    metadata, and the server writes it.
    """

    def __init__(self, bootstrap_options: Options, daemon_entrypoint: str):
        super().__init__(
            name="pantsd",
            metadata_base_dir=bootstrap_options.for_global_scope().pants_subprocessdir,
        )
        self._bootstrap_options = bootstrap_options
        self._daemon_entrypoint = daemon_entrypoint

    @property
    def options_fingerprint(self) -> str:
        """Returns the options fingerprint for the pantsd process.

        This should cover all options consumed by the pantsd process itself in order to start: also
        known as the "micro-bootstrap" options. These options are marked `daemon=True` in the global
        options.

        The `daemon=True` options are a small subset of the bootstrap options. Independently, the
        PantsDaemonCore fingerprints the entire set of bootstrap options to identify when the
        Scheduler needs need to be re-initialized.
        """
        fingerprintable_options = self._bootstrap_options.get_fingerprintable_for_scope(
            GLOBAL_SCOPE, daemon_only=True
        )
        fingerprintable_option_names = {name for name, _, _ in fingerprintable_options}
        return pantsd_fingerprint_compute(fingerprintable_option_names)

    def needs_restart(self, option_fingerprint):
        """Overrides ProcessManager.needs_restart, to account for the case where pantsd is running
        but we want to shutdown after this run.

        :param option_fingerprint: A fingerprint of the global bootstrap options.
        :return: True if the daemon needs to restart.
        """
        return super().needs_restart(option_fingerprint)

    def post_fork_child(self):
        """Post-fork() child callback for ProcessManager.daemon_spawn()."""
        spawn_control_env = {
            DAEMON_ENTRYPOINT: f"{self._daemon_entrypoint}:launch_new_pantsd_instance",
            # The daemon should run under the same sys.path as us; so we ensure
            # this. NB: It will scrub PYTHONPATH once started to avoid infecting
            # its own unrelated subprocesses.
            "PYTHONPATH": os.pathsep.join(sys.path),
        }
        exec_env = {**os.environ, **spawn_control_env}

        # Pass all of sys.argv so that we can proxy arg flags e.g. `-ldebug`.
        cmd = [sys.executable] + sys.argv

        spawn_control_env_vars = " ".join(f"{k}={v}" for k, v in spawn_control_env.items())
        cmd_line = " ".join(cmd)
        logger.debug(f"pantsd command is: {spawn_control_env_vars} {cmd_line}")

        # TODO: Improve error handling on launch failures.
        os.spawnve(os.P_NOWAIT, sys.executable, cmd, env=exec_env)
