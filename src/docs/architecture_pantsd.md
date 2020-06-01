Pants Daemon
============

The Pants Daemon (pantsd) is a system introduced to enable Pants to keep information about the build warm in memory between runs.
It consists of a process running in the background (currently, one for each buildroot), which listens to filesystem events and keeps a build graph warm. It then passes that graph to subsequent runs that request it.

This document outlines all the moving pieces of pantsd, and explains how it works through an end-to-end run.

ProcessManager
--------------

[`ProcessManager`](https://github.com/pantsbuild/pants/blob/master/src/python/pants/pantsd/process_manager.py#223) is a class designed to keep track of processes. Besides changing their state (paused, terminating...), it allows a process to fork in different ways. Classes that extend `ProcessManager` can (and often do) inject code to be run before and after forking by overriding the functions `pre_fork`, `post_fork_child`, `post_fork_parent`. An example of one of these functions is in [`NailgunExecutor`](https://github.com/pantsbuild/pants/blob/aa70d5a3911f78ac9e1f64d2a85ff9dbec1b9dd0/src/python/pants/java/nailgun_executor.py#L296), where we start a Nailgun server that we can connect to, after forking the main Pants process.

The `PantsDaemon` Class
-----------------------

The [`PantsDaemon`](https://github.com/pantsbuild/pants/blob/master/src/python/pants/pantsd/pants_daemon.py#81) class is responsible for managing the lifetime of the pantsd process and the services associated with it. A `PantsDaemon` is created with the inner class [`Factory`](https://github.com/pantsbuild/pants/blob/master/src/python/pants/pantsd/pants_daemon.py#100), and it has two modes of initialization:

- Stub initialization, which parses options, launches watchman, and not much else. This mode is used to determine whether it needs to fully initialize the daemon or not.
- Full initialization, which spawns the daemon process, initializes all the services, the legacy engine and the native code.

Initialization is encapsulated in the `PantsDaemon.Factory.create()` method.
`PantsDaemon` is a `ProcessManager`, which means one can know if it's alive, or if it needs to restart.

`PantsDaemon`s can be `launch()`ed, which will terminate the process it was running, and call `daemon_spawn()` to fork a new process. This new process will run the code in `PantsDaemon.post_fork_child()`, which in short means it will run `os.spawnve` to execute the `pants_daemon.py:launch()` function, which will call `PantsDaemon.run_sync()`. `run_sync()` does a lot of things, but the vital things are calling `_setup_services()` to spin up services, and `_run_services()` to start an infinite loop polling them. More on services later.

Pailgun
-------

The [Nailgun Protocol](http://www.martiansoftware.com/nailgun/protocol.html) is a protocol designed to allow clients to make command-line requests to a [Nailgun Server](http://www.martiansoftware.com/nailgun/index.html). It supports an interface similar to [`Process`](https://github.com/pantsbuild/pants/blob/master/src/python/pants/engine/isolated_process.py#22), except for it having no concern about making operations hermetic, and the Nailgun Protocol supports streaming access to stdin/stdout. Pailgun is an extension of the Nailgun Protocol, which is clients use to ask the Pants Daemon to spawn pants invocations.

The protocol is subject to change slightly in [#6579](https://github.com/pantsbuild/pants/pull/6579).

In Pantsd, [`PailgunServer`](https://github.com/pantsbuild/pants/blob/master/src/python/pants/pantsd/pailgun_server.py#91) is the class responsible for reading Pailgun requests and handling them, by spawning [`PailgunHandler`](https://github.com/pantsbuild/pants/blob/master/src/python/pants/pantsd/pailgun_server.py#52)s in new threads.

Services
--------

A Pants Daemon process has several services that it polls in order. Every service runs in a separate thread, and can be paused, resumed or terminated. Services can communicate with each other.

Examples of services are [`FSEventService`](https://github.com/pantsbuild/pants/blob/master/src/python/pants/pantsd/service/fs_event_service.py#14), which takes care of listening for watchman events, [`SchedulerService`](https://github.com/pantsbuild/pants/blob/master/src/python/pants/pantsd/service/scheduler_service.py#21), which takes care of listening responding to those events to keep a warm `Graph`, and [`PailgunService`](https://github.com/pantsbuild/pants/blob/master/src/python/pants/pantsd/service/pailgun_service.py#15), which listens to `SchedulerService` and manages the lifetime of a `PailgunServer` responsible for spawning pants runs when requested by clients, it takes a `DaemonPantsRunner` as one of its arguments, to use as a template to spawn pants runs when requested by the clients.

### PailgunService
  
A `PailgunService` is a `PantsService` which spins up and polls a `PailgunServer`.
A `PailgunServer` is a `TCPServer` with `ThreadingMixIn`, which listens to Pailgun requests in a socket and spins up instances of `PailgunHandler`s to handle them. It overrides `ThreadingMixIn.process_request_thread()` to spin up one thread and one handler per request. A `PailgunServer` holds a reference to the class `DaemonPantsRunner`, which can be used to run pants from the server.
A `PailgunHandler` is a class that parses the requests sent to the server, and uses `DaemonPantsRunner` to invoke pants with the environment and arguments specified by the request.
A `DaemonPantsRunner` implements a `run()` method that creates an instance of `LocalPantsRunner`, which will be used to run the requested pants command.

An end-to-end run with Pantsd
-----------------------------

To understand what the process is for spinning up and closing down pantsd, here is what happens when we run pantsd for the first time:

If we run the command `./pants --enable-pantsd list src/scala::`, the following happens:

1. `PantsRunner::run()` is called, which will prompt parsing of bootstrap options. `--enable-pantsd` is a bootstrap option.
  * In that function, we determine whether we need to run in pantsd mode or local mode.
    If we choose local mode, an instance of `LocalPantsRunner` is created and the run will continue as if pantsd didn't exist.

2. Since `--enable-pantsd` was toggled on, we will create an instance of `RemotePantsRunner`, and run it. `RemotePantsRunner` will:
  * Maybe launch pantsd, by calling `PantsDaemon.Factory.maybe_launch()`. This method will:
    * Create a stub instance of `PantsDaemon`.
    * Check if any of the fingerprinted options have changed by calling `ProcessManager.needs_restart()`. If they have (or there is no pantsd running at the moment), it will fully initialize an instance of `PantsDaemon` by calling `PantsDaemon.Factory.create()`, and launch it with `PantsDaemon.launch()`. In either case, it will return a `PantsDaemon.Handle` to a process running `PantsDaemon.run_sync()`, which will poll all the services.
  * With a handle to the pantsd process, `RemotePantsRunner` will now call `_run_pants_with_retry()`, which will try to `_connect_and_execute()` to the port supplied by the handle, probably more than once.
  To do that, it will create a `NailgunClient` instance with will use the pailgun protocol described above to tell the pantsd process to invoke pants, with a call along the lines of:
  `result = client.execute('./pants', *self._args, **modified_env)`
  * After that request is finished, it will record the result and the local process will exit. But before that happens, this is what happens from the pantsd side:

3. The `PailgunService` will receive that request, and it will handle it as follows:
  * `PailgunService` is endlessly polling for requests via calling `PailgunServer.handle_request()`.
  * When that method receives a request, it will call `SocketServer._handle_request_noblock()`, which will call `ThreadingMixIn.process_request()` (it would usually call `SocketServer.process_request`, but `PailgunServer` also extends `ThreadingMixIn`, which intentionally overrides this function).
  * `ThreadingMixIn.process_request()` will spin up a new `Thread` and call `PailgunServer.process_request_thread()` (it would usually call `ThreadingMixIn.process_request_thread()`, but we override it).
  * _(note: we are now in a separate thread)_ `PailgunServer.process_request_thread()` will create an instance of `PailgunHandler`, and call `PailgunHandler.handle_request()`.
  * `PailgunHandler.handle_request()` will create an instance of `DaemonPantsRunner`, and it will `run()` it. Creating an instance of `DaemonPantsRunner` with `DaemonPantsRunner.create()` means that it will call the `SchedulerService` to get a warm graph.
  * `DaemonPantsRunner` will create an instance of `LocalPantsRunner` with the graph (and options, and such) it got from the `SchedulerService`, and run as if the daemon didn't exist.

4. The `PailgunServer` will wait until `LocalPantsRunner` is finished in `handle_request`.
