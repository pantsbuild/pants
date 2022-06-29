---
title: "Debugging and benchmarking"
slug: "contributions-debugging"
excerpt: "Some techniques to figure out why Pants is behaving the way it is."
hidden: false
createdAt: "2020-09-04T23:43:34.260Z"
updatedAt: "2022-03-09T16:40:50.789Z"
---
Benchmarking with `hyperfine`
-----------------------------

We use `hyperfine` to benchmark, especially comparing before and after to see the impact of a change: <https://github.com/sharkdp/hyperfine>.

When benchmarking, you must decide if you care about cold cache performance vs. warm cache (or both). If cold, use `--no-pantsd --no-local-cache`. If warm, use hyperfine's option `--warmup=1`.

For example:

```
❯ hyperfine --warmup=1 --runs=5 './pants list ::`
❯ hyperfine --runs=5 './pants --no-pantsd --no-local-cache lint ::'
```

Profiling with py-spy
---------------------

`py-spy` is a profiling sampler which can also be used to compare the impact of a change before and after: <https://github.com/benfred/py-spy>.

To profile with `py-spy`:

1. Activate Pants' development venv
   - `source ~/.cache/pants/pants_dev_deps/<your platform dir>/bin/activate`
2. Add Pants' code to Python's path
   - `export PYTHONPATH=src/pants:$PYTHONPATH`
3. Run Pants with `py-spy` (be sure to disable `pantsd`)
   - `py-spy record --subprocesses -- python -m pants.bin.pants_loader --no-pantsd <pants args>`

The default output is a flamegraph. `py-spy` can also output speedscope (<https://github.com/jlfwong/speedscope>) JSON with the `--format speedscope` flag. The resulting file can be uploaded to <https://www.speedscope.app/> which provides a per-process, interactive, detailed UI.

Additionally, to profile the Rust code the `--native` flag can be passed to `py-spy` as well. The resulting output will contain frames from Pants Rust code.

Identifying the impact of Python's GIL (on macOS)
-------------------------------------------------


[block:embed]
{
  "html": "<iframe class=\"embedly-embed\" src=\"//cdn.embedly.com/widgets/media.html?src=https%3A%2F%2Fwww.youtube.com%2Fembed%2FzALr3zFIQJo%3Ffeature%3Doembed&display_name=YouTube&url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DzALr3zFIQJo&image=https%3A%2F%2Fi.ytimg.com%2Fvi%2FzALr3zFIQJo%2Fhqdefault.jpg&key=f2aa6fc3595946d0afc3d76cbbd25dc3&type=text%2Fhtml&schema=youtube\" width=\"640\" height=\"480\" scrolling=\"no\" title=\"YouTube embed\" frameborder=\"0\" allow=\"autoplay; fullscreen\" allowfullscreen=\"true\"></iframe>",
  "url": "https://www.youtube.com/watch?v=zALr3zFIQJo",
  "title": "Identifying contention on the Python GIL in Rust from macOS",
  "favicon": "https://www.youtube.com/s/desktop/c9a10b09/img/favicon.ico",
  "image": "https://i.ytimg.com/vi/zALr3zFIQJo/hqdefault.jpg",
  "provider": "youtube.com",
  "href": "https://www.youtube.com/watch?v=zALr3zFIQJo"
}
[/block]


Obtaining Full Thread Backtraces
--------------------------------

Pants runs as a Python program that calls into a native Rust library. In debugging locking and deadlock issues, it is useful to capture dumps of the thread stacks in order to figure out where a deadlock may be occurring.

One-time setup:

1. Ensure that gdb is installed.
   - Ubuntu: `sudo apt install gdb`
2. Ensure that the kernel is configured to allow debuggers to attach to processes that are not in the same parent/child process hierarchy.
   - `echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope`
   - To make the change permanent, add a file to /etc/sysctl.d named `99-ptrace.conf` with contents `kernel.yama.ptrace_scope = 0`. **Note: This is a security exposure if you are not normally debugging processes across the process hierarchy.**
3. Ensure that the debug info for your system Python binary is installed.
   - Ubuntu: `sudo apt install python3-dbg`

Dumping thread stacks:

1. Find the pants binary (which may include pantsd if pantsd is enabled).
   - Run: `ps -ef | grep pants`
2. Invoke gdb with the python binary and the process ID:
   - Run: `gdb /path/to/python/binary PROCESS_ID`
3. Enable logging to write the thread dump to `gdb.txt`: `set logging on`
4. Dump all thread backtraces: `thread apply all bt`
5. If you use pyenv to mange your Python install, a gdb script will exist in the same directory as the Python binary. Source it into gdb:
   - `source ~/.pyenv/versions/3.8.5/bin/python3.8-gdb.py` (if using version 3.8.5)
6. Dump all Python stacks: `thread apply all py-bt`
