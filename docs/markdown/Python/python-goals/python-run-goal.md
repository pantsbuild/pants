---
title: "run"
slug: "python-run-goal"
excerpt: "Run a `pex_binary` target."
hidden: false
createdAt: "2020-03-16T16:19:56.403Z"
updatedAt: "2022-01-29T16:45:29.511Z"
---
To run an executable/script, use `./pants run` on a [`pex_binary`](doc:reference-pex_binary) target. (See [package](doc:python-package-goal) for more on the `pex_binary` target.)

```bash
$ ./pants run project/app.py
```

or

```bash
$ ./pants run project:app
```

To pass arguments to the script/executable, use `--` at the end of the command, like this:

```bash
$ ./pants run project/app.py -- --arg1 arg2
```

You may only run one target at a time.

The program will have access to the same environment used by the parent `./pants` process, so you can set environment variables in the external environment, e.g. `FOO=bar ./pants run project/app.py`. (Pants will auto-set some values like `$PATH`).

> 📘 Tip: check the return code
>
> Pants will propagate the return code from the underlying executable. Run `echo $?` after the Pants run to see the return code.

> 🚧 Issues finding files?
>
> Run `./pants dependencies --transitive path/to/binary.py` to ensure that all the files you need are showing up, including for any [assets](doc:assets) you intend to use.

Watching the filesystem
-----------------------

If the app that you are running is long lived and safe to restart (including web apps like Django and Flask or other types of servers/services), you can set `restartable=True` on your `pex_binary` target to indicate this to Pants. The `run` goal will then automatically restart the app when its input files change!

On the other hand, if your app is short lived (like a script) and you'd like to re-run it when files change but never interrupt an ongoing run, consider using `./pants --loop run` instead. See [Goals](doc:goals#running-goals) for more information on `--loop`.

Debugging
---------

> 📘 Tip: using the VS Code (or any [DAP](https://microsoft.github.io/debug-adapter-protocol/)-compliant editor) remote debugger
>
>
> 1. In your editor, set your breakpoints and any other debug settings (like break-on-exception).
> 2. Run your code with `./pants run --debug-adapter`.
> 3. Connect your editor to the server. The server host and port are logged by Pants when executing `run --debug-adaptor`. (They can also be configured using the `[debug-adapter]` subsystem).

> 📘 Tip: Using the IntelliJ/PyCharm remote debugger
>
> First, add the following target in some BUILD file (e.g., the one containing your other 3rd-party dependencies):
>
> ```
> python_requirement(
>   name = "pydevd-pycharm",
>   requirements=["pydevd-pycharm==203.5419.8"],  # Or whatever version you choose.
> )
> ```
>
> You can check this into your repo, for convenience.
>
> Now, use the remote debugger as usual:
>
> 1. Start a Python remote debugging session in PyCharm, say on port 5000.
> 2. Add the following code at the point where you want execution to pause and connect to the debugger:
>
> ```
> import pydevd_pycharm
> pydevd_pycharm.settrace('localhost', port=5000, stdoutToServer=True, stderrToServer=True)
> ```
>
> Run your executable with `./pants run` as usual.
>
> Note: The first time you do so you may see some extra dependency resolution work, as `pydevd-pycharm` has now been added to the binary's dependencies, via inference. If you have dependency inference turned off in your repo, you will have to manually add a temporary explicit dependency in your binary target on the `pydevd-pycharm` target.
