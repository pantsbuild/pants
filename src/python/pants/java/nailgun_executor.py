# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import logging
import os
import re
import selectors
import threading
import time
from contextlib import closing

from pants.base.build_environment import get_buildroot
from pants.java.executor import Executor, SubprocessExecutor
from pants.java.nailgun_client import NailgunClient
from pants.pantsd.process_manager import FingerprintedProcessManager, ProcessGroup
from pants.util.collections import ensure_str_list
from pants.util.dirutil import read_file, safe_file_dump, safe_open
from pants.util.memo import memoized_classproperty

logger = logging.getLogger(__name__)


class NailgunProcessGroup(ProcessGroup):
    _NAILGUN_KILL_LOCK = threading.Lock()

    def __init__(self, metadata_base_dir=None):
        super().__init__(name="nailgun", metadata_base_dir=metadata_base_dir)
        # TODO: this should enumerate the .pids dir first, then fallback to ps enumeration (& warn).

    def _iter_nailgun_instances(self, everywhere=False):
        def predicate(proc):
            if proc.name() == NailgunExecutor._PROCESS_NAME:
                if not everywhere:
                    return NailgunExecutor._PANTS_NG_BUILDROOT_ARG in proc.cmdline()
                else:
                    return any(
                        arg.startswith(NailgunExecutor._PANTS_NG_ARG_PREFIX)
                        for arg in proc.cmdline()
                    )

        return self.iter_instances(predicate)

    def killall(self, everywhere=False):
        """Kills all nailgun servers started by pants.

        :param bool everywhere: If ``True``, kills all pants-started nailguns on this machine;
                                otherwise restricts the nailguns killed to those started for the
                                current build root.
        """
        with self._NAILGUN_KILL_LOCK:
            for proc in self._iter_nailgun_instances(everywhere):
                logger.info("killing nailgun server pid={pid}".format(pid=proc.pid))
                proc.terminate()


# TODO: Once we integrate standard logging into our reporting framework, we can consider making
# some of the log.debug() below into log.info(). Right now it just looks wrong on the console.
class NailgunExecutor(Executor, FingerprintedProcessManager):
    """Executes java programs by launching them in nailgun server.

    If a nailgun is not available for a given set of jvm args and classpath, one is launched and re-
    used for the given jvm args and classpath on subsequent runs.
    """

    # 'NGServer 0.9.1 started on 127.0.0.1, port 53785.'
    _NG_PORT_REGEX = re.compile(r".*\s+port\s+(\d+)\.$")

    # Used to identify if we own a given nailgun server.
    FINGERPRINT_CMD_KEY = "-Dpants.nailgun.fingerprint"
    _PANTS_NG_ARG_PREFIX = "-Dpants.buildroot"
    _PANTS_OWNER_ARG_PREFIX = "-Dpants.nailgun.owner"

    @memoized_classproperty
    def _PANTS_NG_BUILDROOT_ARG(cls):
        return "=".join((cls._PANTS_NG_ARG_PREFIX, get_buildroot()))

    _NAILGUN_SPAWN_LOCK = threading.Lock()
    _PROCESS_NAME = "java"

    def __init__(
        self,
        identity,
        workdir,
        nailgun_classpath,
        distribution,
        startup_timeout=10,
        connect_timeout=10,
        connect_attempts=5,
        metadata_base_dir=None,
    ):
        Executor.__init__(self, distribution=distribution)
        FingerprintedProcessManager.__init__(
            self,
            name=identity,
            process_name=self._PROCESS_NAME,
            metadata_base_dir=metadata_base_dir,
        )

        if not isinstance(workdir, str):
            raise ValueError(
                "Workdir must be a path string, not: {workdir}".format(workdir=workdir)
            )

        self._identity = identity
        self._workdir = workdir
        self._ng_stdout = os.path.join(workdir, "stdout")
        self._ng_stderr = os.path.join(workdir, "stderr")
        self._nailgun_classpath = ensure_str_list(nailgun_classpath, allow_single_str=True)
        self._startup_timeout = startup_timeout
        self._connect_timeout = connect_timeout
        self._connect_attempts = connect_attempts

    def __str__(self):
        return "NailgunExecutor({identity}, dist={dist}, pid={pid} socket={socket})".format(
            identity=self._identity, dist=self._distribution, pid=self.pid, socket=self.socket
        )

    def _create_owner_arg(self, workdir):
        # Currently the owner is identified via the full path to the workdir.
        return "=".join((self._PANTS_OWNER_ARG_PREFIX, workdir))

    def _create_fingerprint_arg(self, fingerprint):
        return "=".join((self.FINGERPRINT_CMD_KEY, fingerprint))

    @staticmethod
    def _fingerprint(jvm_options, classpath, java_version):
        """Compute a fingerprint for this invocation of a Java task.

        :param list jvm_options: JVM options passed to the java invocation
        :param list classpath: The -cp arguments passed to the java invocation
        :param Revision java_version: return value from Distribution.version()
        :return: a hexstring representing a fingerprint of the java invocation
        """
        digest = hashlib.sha1()
        # TODO(John Sirois): hash classpath contents?
        encoded_jvm_options = [option.encode() for option in sorted(jvm_options)]
        encoded_classpath = [cp.encode() for cp in sorted(classpath)]
        encoded_java_version = repr(java_version).encode()
        for item in (encoded_jvm_options, encoded_classpath, encoded_java_version):
            digest.update(str(item).encode())
        return digest.hexdigest()

    def _runner(self, classpath, main, jvm_options, args):
        """Runner factory.

        Called via Executor.execute().
        """
        command = self._create_command(classpath, main, jvm_options, args)

        class Runner(self.Runner):
            @property
            def executor(this):
                return self

            @property
            def command(self):
                return list(command)

            def run(this, stdout=None, stderr=None, stdin=None, cwd=None):
                nailgun = None
                try:
                    nailgun = self._get_nailgun_client(
                        jvm_options, classpath, stdout, stderr, stdin
                    )
                    logger.debug(
                        "Executing via {ng_desc}: {cmd}".format(ng_desc=nailgun, cmd=this.cmd)
                    )
                    return nailgun.execute(main, cwd, *args)
                except (NailgunClient.NailgunError, self.InitialNailgunConnectTimedOut) as e:
                    self.terminate()
                    raise self.Error(
                        "Problem launching via {ng_desc} command {main} {args}: {msg}".format(
                            ng_desc=nailgun or "<no nailgun connection>",
                            main=main,
                            args=" ".join(args),
                            msg=e,
                        )
                    )

        return Runner()

    def _check_nailgun_state(self, new_fingerprint):
        running = self.is_alive()
        updated = self.needs_restart(new_fingerprint)
        logging.debug(
            "Nailgun {nailgun} state: updated={up!s} running={run!s} fingerprint={old_fp} "
            "new_fingerprint={new_fp} distribution={old_dist} new_distribution={new_dist}".format(
                nailgun=self._identity,
                up=updated,
                run=running,
                old_fp=self.fingerprint,
                new_fp=new_fingerprint,
                old_dist=self.cmd,
                new_dist=self._distribution.java,
            )
        )
        return running, updated

    def _get_nailgun_client(self, jvm_options, classpath, stdout, stderr, stdin):
        """This (somewhat unfortunately) is the main entrypoint to this class via the Runner.

        It handles creation of the running nailgun server as well as creation of the client.
        """
        classpath = self._nailgun_classpath + classpath
        new_fingerprint = self._fingerprint(jvm_options, classpath, self._distribution.version)

        with self._NAILGUN_SPAWN_LOCK:
            running, updated = self._check_nailgun_state(new_fingerprint)

            if running and updated:
                logger.debug(
                    "Found running nailgun server that needs updating, killing {server}".format(
                        server=self._identity
                    )
                )
                self.terminate()

            if (not running) or (running and updated):
                return self._spawn_nailgun_server(
                    new_fingerprint, jvm_options, classpath, stdout, stderr, stdin
                )

        return self._create_ngclient(port=self.socket, stdout=stdout, stderr=stderr, stdin=stdin)

    class InitialNailgunConnectTimedOut(Exception):
        _msg_fmt = """Failed to read nailgun output after {timeout} seconds!
Stdout:
{stdout}
Stderr:
{stderr}"""

        def __init__(self, timeout, stdout, stderr):
            msg = self._msg_fmt.format(timeout=timeout, stdout=stdout, stderr=stderr)
            super(NailgunExecutor.InitialNailgunConnectTimedOut, self).__init__(msg)

    def _await_socket(self, timeout):
        """Blocks for the nailgun subprocess to bind and emit a listening port in the nailgun
        stdout."""
        start_time = time.time()
        accumulated_stdout = ""

        def calculate_remaining_time():
            return time.time() - (start_time + timeout)

        def possibly_raise_timeout(remaining_time):
            if remaining_time > 0:
                stderr = read_file(self._ng_stderr, binary_mode=True)
                raise self.InitialNailgunConnectTimedOut(
                    timeout=timeout, stdout=accumulated_stdout, stderr=stderr,
                )

        # NB: We use PollSelector, rather than the more efficient DefaultSelector, because
        # DefaultSelector results in using the epoll() syscall on Linux, which does not work with
        # regular text files like ng_stdout. See https://stackoverflow.com/a/8645770.
        with selectors.PollSelector() as selector, safe_open(self._ng_stdout, "r") as ng_stdout:
            selector.register(ng_stdout, selectors.EVENT_READ)
            while 1:
                remaining_time = calculate_remaining_time()
                possibly_raise_timeout(remaining_time)
                events = selector.select(timeout=-1 * remaining_time)
                if events:
                    line = ng_stdout.readline()  # TODO: address deadlock risk here.
                    try:
                        return self._NG_PORT_REGEX.match(line).group(1)
                    except AttributeError:
                        pass
                    accumulated_stdout += line

    def _create_ngclient(self, port, stdout, stderr, stdin):
        return NailgunClient(port=port, ins=stdin, out=stdout, err=stderr)

    def ensure_connectable(self, nailgun):
        """Ensures that a nailgun client is connectable or raises NailgunError."""
        attempt_count = 1
        while 1:
            try:
                with closing(nailgun.try_connect()) as sock:
                    logger.debug(
                        "Verified new ng server is connectable at {}".format(sock.getpeername())
                    )
                    return
            except nailgun.NailgunConnectionError:
                if attempt_count >= self._connect_attempts:
                    logger.debug(
                        "Failed to connect to ng after {} attempts".format(self._connect_attempts)
                    )
                    raise  # Re-raise the NailgunConnectionError which provides more context to the user.

            attempt_count += 1
            time.sleep(self.WAIT_INTERVAL_SEC)

    def _spawn_nailgun_server(self, fingerprint, jvm_options, classpath, stdout, stderr, stdin):
        """Synchronously spawn a new nailgun server."""
        # Truncate the nailguns stdout & stderr.
        safe_file_dump(self._ng_stdout, b"", mode="wb")
        safe_file_dump(self._ng_stderr, b"", mode="wb")

        jvm_options = jvm_options + [
            self._PANTS_NG_BUILDROOT_ARG,
            self._create_owner_arg(self._workdir),
            self._create_fingerprint_arg(fingerprint),
        ]

        post_fork_child_opts = dict(
            fingerprint=fingerprint,
            jvm_options=jvm_options,
            classpath=classpath,
            stdout=stdout,
            stderr=stderr,
        )

        logger.debug(
            "Spawning nailgun server {i} with fingerprint={f}, jvm_options={j}, classpath={cp}".format(
                i=self._identity, f=fingerprint, j=jvm_options, cp=classpath
            )
        )

        self.daemon_spawn(post_fork_child_opts=post_fork_child_opts)

        # Wait for and write the port information in the parent so we can bail on exception/timeout.
        self.await_pid(self._startup_timeout)
        self.write_socket(self._await_socket(self._connect_timeout))

        logger.debug(
            "Spawned nailgun server {i} with fingerprint={f}, pid={pid} port={port}".format(
                i=self._identity, f=fingerprint, pid=self.pid, port=self.socket
            )
        )

        client = self._create_ngclient(port=self.socket, stdout=stdout, stderr=stderr, stdin=stdin)
        self.ensure_connectable(client)

        return client

    def _check_process_buildroot(self, process):
        """Matches only processes started from the current buildroot."""
        return self._PANTS_NG_BUILDROOT_ARG in process.cmdline()

    def is_alive(self):
        """A ProcessManager.is_alive() override that ensures buildroot flags are present in the
        process command line arguments."""
        return super().is_alive(self._check_process_buildroot)

    def post_fork_child(self, fingerprint, jvm_options, classpath, stdout, stderr):
        """Post-fork() child callback for ProcessManager.daemon_spawn()."""
        java = SubprocessExecutor(self._distribution)

        subproc = java.spawn(
            classpath=classpath,
            main="com.martiansoftware.nailgun.NGServer",
            jvm_options=jvm_options,
            args=[":0"],
            stdin=safe_open("/dev/null", "r"),
            stdout=safe_open(self._ng_stdout, "w"),
            stderr=safe_open(self._ng_stderr, "w"),
            close_fds=True,
        )

        self.write_pid(subproc.pid)
