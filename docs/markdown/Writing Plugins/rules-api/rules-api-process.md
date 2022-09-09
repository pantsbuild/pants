---
title: "Processes"
slug: "rules-api-process"
excerpt: "How to safely run subprocesses in your plugin."
hidden: false
createdAt: "2020-05-07T22:38:44.131Z"
updatedAt: "2022-04-26T22:24:24.966Z"
---
It is not safe to use `subprocess.run()` like you normally would because this can break caching and will not leverage Pants's parallelism. Instead, Pants has safe alternatives with `Process` and `InteractiveProcess`.

`Process`
---------

### Overview

`Process` is similar to Python's `subprocess.Popen()`. The process will run in the background, and you can run multiple processes in parallel.

```python
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, rule

@rule
async def demo(...) -> Foo:
    result = await Get(
        ProcessResult,
        Process(
            argv=["/bin/echo", "hello world"],
            description="Demonstrate processes.",
        )
    )
    logger.info(result.stdout.decode())
    logger.info(result.stderr.decode())
```

This will return a `ProcessResult` object, which has the fields `stdout: bytes`, `stderr: bytes`, and `output_digest: Digest`. 

The process will run in a temporary directory and is hermetic, meaning that it cannot read any arbitrary file from your project and that it will be stripped of environment variables. This sandbox is important for reproducibility and to allow running your `Process` anywhere, such as through remote execution.

> 📘 Debugging a `Process`
> 
> Setting the [`--keep-sandboxes=always`](doc:rules-api-tips#debugging-look-inside-the-chroot) flag will cause the sandboxes of `Process`es to be preserved and logged to the console for inspection.
> 
> It can be very helpful while editing `Process` definitions!

### Input Files

To populate the temporary directory with files, use the parameter `input_digest: Digest`. It's common to use [`MergeDigests`](doc:rules-api-file-system) to combine multiple `Digest`s into one single `input_digest`.

### Environment Variables

To set environment variables, use the parameter `env: Mapping[str, str]`. `@rules` are prevented from accessing `os.environ` (it will always be empty) because this reduces reproducibility and breaks caching. Instead, either hardcode the value or add a [`Subsystem` option](doc:rules-api-subsystems) for the environment variable in question, or request the `Environment` type in your `@rule`.

The `Environment` type contains a subset of the environment that Pants was run in, and is requested via a `EnvironmentRequest` that lists the variables to consume.

```python
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.rules import Get, rule

@rule
async def partial_env(...) -> Foo:
    relevant_env = await Get(Environment, EnvironmentRequest(["RELEVANT_VAR", "PATH"]))
    ..
```

### Output Files

To capture output files from the process, set `output_files: Iterable[str]` and/or `output_directories: Iterable[str]`. Then, you can use the `ProcessResult.output_digest` field to get a [`Digest`](doc:rules-api-file-system) of the result.

`output_directores` captures that directory and everything below it.

### Timeouts

To use a timeout, set the `timeout_seconds: int` field. Otherwise, the process will never time out, unless the user cancels Pants.

> 📘 `Process` caching
> 
> By default, a `Process` will be cached to `~/.cache/pants/lmdb_store` if the `exit_code` is `0`.
> 
> If it not safe to cache your `Process`—usually the case when you know that a process accesses files outside of its sandbox—you can change the cacheability of your `Process` using the `ProcessCacheScope` parameter:
> 
> ```python
> from pants.engine.process import Process, ProcessCacheScope, ProcessResult
> 
> @rule
> async def demo(...) -> Foo:
>     process = Process(
>         argv=["/bin/echo", "hello world"],
>         description="Not persisted between Pants runs ('sessions').",
>         cache_scope=ProcessCacheScope.PER_SESSION,
>     )
>     ..
> ```
> 
> `ProcessCacheScope` supports other options as well, including `ALWAYS`.

### FallibleProcessResult

Normally, a `ProcessResult` will raise an exception if the return code is not `0`. Instead, a `FallibleProcessResult` allows for any return code.

Use `Get(FallibleProcessResult, Process)` if you expect that the process may fail, such as when running a linter or tests.

Like `ProcessResult`, `FallibleProcessResult` has the attributes `stdout: bytes`, `stderr: bytes`, and `output_digest: Digest`, and it adds `exit_code: int`.

`InteractiveProcess`
--------------------

`InteractiveProcess` is similar to Python's `subprocess.run()`. The process will run in the foreground, optionally with access to the workspace.

Because the process is potentially side-effecting, you may only run an `InteractiveProcess` in an [`@goal_rule`](doc:rules-api-goal-rules) as an `Effect`.

```python
from pants.engine.rules import Effect, goal_rule
from pants.engine.process import InteractiveProcess, InteractiveProcessResult

@goal_rule
async def hello_world() -> HelloWorld:
    # This demonstrates opening a Python REPL.
    result = await Effect(
        InteractiveProcessResult,
        InteractiveProcess(argv=["/usr/bin/python"]),
    )
    return HelloWorld(exit_code=result.exit_code)
```

You may either set the parameter `input_digest: Digest`, or you may set `run_in_workspace=True`. When running in the workspace, you will have access to any file in the build root. If the process can safely be restarted, set the `restartable=True` flag, which will allow the engine to interrupt and restart the process if its inputs have changed.

To set environment variables, use the parameter `env: Mapping[str, str]`, like you would with `Process`. You can also set `hermetic_env=False` to inherit the environment variables from the parent `./pants` process.

The `Effect` will return an `InteractiveProcessResult`, which has a single field `exit_code: int`.
