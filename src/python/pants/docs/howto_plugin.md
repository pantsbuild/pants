Developing a Pants Plugin
=========================

*As of September 2014, this process is new and still evolving;* *expect
it to change somewhat.*

This page documents how to develop a Pants plugin, a set of code that
defines new Pants functionality. If you
[[develop a new task|pants('src/python/pants/docs:dev_tasks')]]
or target to add to Pants (or to
override an existing part of Pants), a plugin gives you a way to
register your code with Pants.

Much of Pants' own functionality is organized in plugins; see them in
[`src/python/pants/backend/*`](https://github.com/pantsbuild/pants/tree/master/src/python/pants/backend).

A plugin registers its functionality with Pants by defining some
functions in a `register.py` file in its top directory. For example,
Pants' `jvm` code registers in
[src/python/pants/backend/jvm/register.py](https://github.com/pantsbuild/pants/blob/master/src/python/pants/backend/jvm/register.py)
Pants' backend-loader code assumes your plugin has a `register.py` file
there.

Simple Configuration
--------------------

If you want to extend Pants without adding any 3rd Party libraries that aren't already referenced by
Pants, you can use the following technique using sources stored directly
in your repo.  All you need to do is add the directory where your plugin sources are stored
to `PYTHONPATH` and put the package where the plugin is defined in `pants.ini`.

In the example below, the stock `JvmBinary` target will subclassed so that a custom task (not shown)
can consume it specifically but disregard regular `JvmBinary` instances (using `isinstance()`).

- Define a home for your plugins. In this example we'll use a directory named 'plugins'

- Create an empty  `plugins/hadoop_binary/target/__init__.py` to define your python package.
  Also create empty `__init__.py` files in each directory up to but not including the root
  directory of your python package layout.

- Create a python module `plugins/hadoop_binary/target/hadoop_binary.py`:

        :::python
        # plugins/target/hadoop_binary.py
        from pants.backend.jvm.targets.jvm_binary import JvmBinary


        class HadoopBinary(JvmBinary):
          pass


- Create `plugins/hadoop_binary/register.py` to register the functions in your plugin.  When registering a
backend in pants.ini, register.py is used by the pants plugin api to register new functions
exposed in build files, targets, tasks and goals:

        :::python
        # plugins/hadoop_binary/register.py

        from pants.build_graph.build_file_aliases import BuildFileAliases
        from hadoop_binary.target import HadoopBinary

        def build_file_aliases():
          return BuildFileAliases(
            targets={
              'hadoop_binary': HadoopBinary,
            },
          )

- Update your `pants` wrapper script to include the `plugins/` directory on `PYTHONPATH`:

        :::bash
        PYTHONPATH=plugins:${PYTHONPATH}
        export PYTHONPATH

- In `pants.ini`, add your new plugins directory to the list of backends to load when pants starts.
This instructs pants to look for a module named `hadoop_binary.register` and invoke
it.

        :::python
        [DEFAULT]
        backend_packages: [
            "hadoop_binary",
          ]

Examples from `twitter/commons`
-------------------------------

For an example of a code repo with plugins to add features to Pants when building in that repo,
take a look at [`twitter/commons`](https://github.com/twitter/commons), especially its
[`pants-plugin` directory](https://github.com/twitter/commons).

This repo has a [`pants` wrapper script](https://github.com/twitter/commons/blob/master/pants)
that script adds `pants-plugins/src/python` to `PYTHONPATH`.

The repo's [`pants.ini` file](https://github.com/twitter/commons/blob/master/pants) has a
`backend_packages` entry listing the plugin packages (packages with `register.py` files):

    :::python
    [DEFAULT]
    backend_packages: [
        'twitter.common.pants.jvm.args',
        'twitter.common.pants.jvm.extras',
        'twitter.common.pants.python.commons',
    ]

The [`...jvm/extras/register.py`](https://github.com/twitter/commons/blob/master/pants-plugins/src/python/twitter/common/pants/jvm/extras/register.py)
file registers a `checkstyle` goal. To find the code for this task, come back to the
`pantsbuild/pants` repo: Pants defines the
[`Checkstyle` task class](https://github.com/pantsbuild/pants/blob/master/src/python/pants/backend/jvm/tasks/checkstyle.py) but doesn't register it. But other Pants workspaces can register it, as
`twitter/commons` illustrates.

The [`...jvm/args/register.py`](https://github.com/twitter/commons/blob/master/pants-plugins/src/python/twitter/common/pants/jvm/args/register.py)
registers a goal, `args-apt`. This plugin also defines the
[`Task` class for this goal](https://github.com/twitter/commons/blob/master/pants-plugins/src/python/twitter/common/pants/jvm/args/tasks/resource_mapper.py).

(Somewhat confusingly, `twitter/commons`' has a `BUILD` file so it can publish its plugins as a
`setup_py` artifact. If you only use your plugin to build code in the *same* workspace,
your plugin directory tree does *not* need any `BUILD` files. By publishing this plugin, Twitter can
use its code in other workspaces, e.g., Twitter's internal codebase. Other folks can use it too:
introduce a dependency on `twitter.common.pants` and add entries to their `pants.ini backend_packages`
section.)

