# Python development using Pants #

brian wickman

@wickman

[TOC]


# Why use Pants for Python development? #

Pants makes the manipulation and distribution of hermetically sealed Python environments
painless.

But why another system?

## Alternatives ##

There are several solutions for package management in Python.  Almost
everyone is familiar with running `sudo easy_install PackageXYZ`.  This
leaves a lot to be desired.  Over time, your Python installation will
collect dozens of packages, become annoyingly slow or even broken, and
reinstalling it will invariably break a number of the applications
that you were using.

A marked improvement over the `sudo easy_install` model is
[virtualenv](http://www.virtualenv.org) to isolate Python environments on a
project by project basis.  This is useful for development but does not
directly solve any problems related to deployment, whether it be to a production
environment or to your peers.  It is also challenging to explain to a
Python non-expert.

A different solution altogether, [zc.buildout](http://www.buildout.org/)
attempts to provide a framework and recipes for many common development
environments.  It has arguably gone the farthest for automating environment
reproducibility amongst the popular tools, but shares the same complexity
problems as all the other abovementioned solutions.

Most solutions leave deployment as an afterthought.  Why not make the
development and deployment environments the same by taking the environment
along with you?

## Pants and PEX ##

The lingua franca of Pants is the PEX file (PEX itself does not stand for
anything in particular, though in spirit you can think of it as a "Python
EXecutable".)

**PEX files are single-file lightweight virtual Python environments.**

The only difference is no virtualenv setup instructions or
`pip install foo bar baz`.  PEX files are self-bootstrapping Python
environments with no strings attached and no side-effects.  Just a simple
mechanism that unifies both your development and your deployment.


# Getting started #

First it is necessary to install Pants.  See [[installation instructions|pants('src/python/twitter/pants:install')]].

It is also helpful to read the main Pants [[README|pants('src/python/twitter/pants:readme')]].


# TL;DR - 'Hello world!' with Pants Python #

```console
$ git clone git://github.com/twitter/commons
$ cd commons
$ mkdir -p src/python/twitter/my_project
$ vi src/python/twitter/my_project/BUILD
```

`src/python/twitter/my_project/BUILD`:

```python
python_binary(
  name = 'hello_world',
  source = 'hello_world.py'
)
```

```console
$ vi src/python/twitter/my_project/hello_world.py
```

`src/python/twitter/my_project/hello_world.py`:

```python
print('Hello world!')
```

To run directly:

```console
$ ./pants py src/python/twitter/my_project:hello_world
Build operating on target: PythonBinary(src/python/twitter/my_project/BUILD:hello_world)
Hello world!
```

To build:

```console
$ ./pants src/python/twitter/my_project:hello_world
Build operating on targets: OrderedSet([PythonBinary(src/python/twitter/my_project/BUILD:hello_world)])
Building PythonBinary PythonBinary(src/python/twitter/my_project/BUILD:hello_world):
Wrote /Users/wickman/clients/science-py-csl/dist/hello_world.pex
```

and run separately:

```console
$ dist/hello_world.pex
Hello world!
```

NOTE: The first time you run `./pants` will likely take a ridiculous amount
of time as Pants bootstraps itself inside your directory.  Note, it never
installs anything in a global site-packages.


# Describing Python environments in Pants ##

Build dependencies in Pants are managed with `BUILD` files that are
co-located with your source.  These files are used to describe the following:

1. libraries:  bundles of sources and resources, that may or may not also depend on other libraries
2. binaries:  a single source (the executable) and libraries it depends upon
3. requirements:  external dependencies as resolved by dependency managers e.g. pypi in Python or ivy on the JVM

The main point of Pants is to take these `BUILD` files and do something useful with them.


## BUILD file format ##

These descriptions are stored in files named BUILD and colocated near the
binaries/libraries they describe.  Let's take for example the
src/python/twitter/tutorial subtree in commons:

```console
$ ls -lR src/python/twitter/tutorial/
total 16
-rw-r--r--  1 wickman  wheel  137 Apr  9 22:59 BUILD
-rw-r--r--  1 wickman  wheel  118 Apr  9 22:59 hello_world.py
```

Let's take a look at the BUILD file in `src/python/twitter/tutorial/BUILD`:

```python
python_binary(
  name = "hello_world",
  source = "hello_world.py",
  dependencies = [
    pants("src/python/twitter/common/app"),
  ]
)
```

This BUILD file names one target: `hello_world`, which is a `python_binary` target.  The `hello_world` target
contains one source file, `hello_world.py` and depends upon one other
target, the format of which will be described shortly.

It should be noted that sources are relative to the location of the BUILD
file itself, e.g.  `hello_world.py` inside of `src/python/twitter/tutorial/BUILD` actually refers to
`src/python/twitter/tutorial/hello_world.py`:

```python
from twitter.common import app

def main():
  print('Hello world!')

app.main()
```

Dependencies, on the other hand, are relative to the *source root* of the repository which is defined
by the BUILD file that sits next to the `pants` command:

```python
# Define the repository layout

source_root('src/antlr', doc, page, python_antlr_library)
source_root('src/java', annotation_processor, doc, jvm_binary, java_library, page)
source_root('src/protobuf', doc, java_protobuf_library, page)
source_root('src/python', doc, page, python_binary, python_library)
source_root('src/scala', doc, jvm_binary, page, scala_library)
source_root('src/thrift', doc, java_thrift_library, page, python_thrift_library)

source_root('tests/java', doc, java_library, java_tests, page)
source_root('tests/python', doc, page, python_library, python_tests, python_test_suite)
source_root('tests/scala', doc, page, scala_library, scala_tests)
```

This file can be tailored to map to any source root structure such as Maven
style, Twitter style (as described above) or something more flat such as a
`setup.py`-based project.  This however is an advanced topic that is not
covered in this document.


## Addressing targets ##

Within the `src/python/twitter/tutorial/BUILD`, only one target is defined,
specifically `hello_world`.  This target is addressed by
`src/python/twitter/tutorial:hello_world` which means the target
`hello_world` within `src/python/twitter/tutorial/BUILD`.  In general,
targets take the form `<path>:<target name>` with the special cases:

1. in the case of `path/to/directory/BUILD:target`, the `BUILD` component may be elided and instead `path/to/directory:target` may be used
2. `path/to/directory` is short form for `path/to/directory:directory`, so `src/python/twitter/common/app` is short form for `src/python/twitter/common/app/BUILD:app`

`src/python/twitter/tutorial/BUILD` referenced `pants('src/python/twitter/common/app')` in its
dependencies.  The `pants()` keyword is akin to a "pointer dereference" for an address.  It will point
to whatever target is described at that address, in this case a `python_library` target:

`src/python/twitter/common/app/BUILD`:

```python
python_library(
  name = "app",
  sources = globs('*.py'),
  dependencies = [
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/common/options'),
    pants('src/python/twitter/common/util'),
    pants('src/python/twitter/common/app/modules'),
  ]
)
```

which in turn includes even more dependencies.  The job of Pants is to manage the transitive closure
of all these dependencies and manipulate collections of these targets for you.


## Python target types ##

BUILD files themselves are just Python.  The only thing magical is that the
statement `from twitter.pants import *` has been autoinjected.  This
provides a number of Python-specific targets such as:

1. `python_library`
2. `python_binary`
3. `python_requirement`
4. `python_thrift_library`

and a whole host of other targets including Java, Scala, Python, Markdown,
the universal `pants` target and so forth.  See
`src/python/twitter/pants/__init__.py` for a comprehensive list of targets.


### `python_library` ###

A `python_library` target has a name, zero or more source files, zero or
more resource files, and zero or more dependencies.  These dependencies may
include other `python_library`-like targets (`python_library`,
`python_thrift_library`, `python_antlr_library` and so forth) or
`python_requirement` targets.


### `python_binary` ###

A `python_binary` target is almost identical to a `python_library` target except instead of `sources`, it takes one
of two possible parameters:

1. `source`: The source file that should be executed within the "library" otherwise defined by `python_binary`
2. `entry_point`: The entry point that should be executed within the "library" otherwise defined by `python_binary`.  Entry points take the
format of `pkg_resources.EntryPoint`, which is something akin to `some.module.name:my.attr` which means
run the function pointed by `my.attr` inside the module `some.module` inside the environment.
The `:my.attr` component can be omitted and the module is executed directly (presuming it has a `__main__.py`.)


### `python_requirement` ###

A `python_requirement` target describes an external dependency as understood by easy_install or pip.  It takes only
a single non-keyword argument of the `Requirement`-style string, e.g.

```python
python_requirement('django-celery')
python_requirement('tornado==2.2')
python_requirement('kombu>=2.1.1,<3.0')
```

This will resolve the dependency and its transitive closure, for example `django-celery` pulls down the following
dependencies: `celery>=2.5.1`, `django-picklefield>=0.2.0`, `ordereddict`, `python-dateutil`,
`kombu>=2.1.1,<3.0`, `anyjson>=0.3.1`, `importlib`, and `amqplib>=1.0`.

Pants takes care of handling these dependencies for you.  It will never install anything globally.  Instead it will
build the dependency and cache it in `.pants.d` and assemble them a la carte into an execution environment.


### `python_thrift_library` ###

A `python_thrift_library` target takes the same arguments as `python_library` arguments, except that files described
in `sources` must be thrift files.  If your library or binary depends upon this target type, Python bindings
will be autogenerated and included within your environment.



# Building your first PEX #

Now you're ready to build your first PEX file (technically you already have,
by building Pants itself.)  By default if you specify `./pants <target>`, it
assumes you mean `./pants build <target>` and does precisely that:

```console
$ PANTS_VERBOSE=1 ./pants src/python/twitter/tutorial:hello_world
Build operating on targets: OrderedSet([PythonBinary(src/python/twitter/tutorial/BUILD:hello_world)])
  Resolver: Calling environment super => 0.046ms
Building PythonBinary PythonBinary(src/python/twitter/tutorial/BUILD:hello_world):
Building PythonBinary PythonBinary(src/python/twitter/tutorial/BUILD:hello_world):
  Dumping library: PythonLibrary(src/python/twitter/common/app/BUILD:app) [relative module: ]
  Dumping library: PythonLibrary(src/python/twitter/common/dirutil/BUILD:dirutil) [relative module: ]
  Dumping library: PythonLibrary(src/python/twitter/common/lang/BUILD:lang) [relative module: ]
  Dumping library: PythonLibrary(src/python/twitter/common/options/BUILD:options) [relative module: ]
  Dumping library: PythonLibrary(src/python/twitter/common/util/BUILD:util) [relative module: ]
  Dumping library: PythonLibrary(src/python/twitter/common/app/modules/BUILD:modules) [relative module: ]
  Resolver: Calling environment super => 0.016ms
  Dumping binary: twitter/tutorial/hello_world.py
Wrote /private/tmp/wickman-commons/dist/hello_world.pex
```

You will see that despite specifying just one dependency, the transitive
closure of `hello_world` pulled in all of `src/python/twitter/common/app`
and its direct descendants.  That's because those library targets depended
upon other library targets, than in turn depending on even more.  At the end
of the day, we bundle up the closed set of all dependencies and bundle them
into `hello_world.pex`.

Since it uses the `twitter.common.app` framework, we know we can fire it up
and poke around with `--help`:

```console
$ dist/hello_world.pex --help
Options:
  -h, --help, --short-help
                        show this help message and exit.
  --long-help           show options from all registered modules, not just the
                        __main__ module.
```

If we specify `--long-help`, we can see the help of transitively included
modules, e.g.  `twitter.common.app` itself:

```console
$ dist/hello_world.pex --long-help
Options:
  -h, --help, --short-help
                        show this help message and exit.
  --long-help           show options from all registered modules, not just the
                        __main__ module.

  From module twitter.common.app:
    --app_daemonize     Daemonize this application. [default: False]
    --app_profile_output=FILENAME
                        Dump the profiling output to a binary profiling
                        format. [default: None]
    --app_daemon_stderr=TWITTER_COMMON_APP_DAEMON_STDERR
                        Direct this app's stderr to this file if daemonized.
                        [default: /dev/null]
    --app_debug         Print extra debugging information during application
                        initialization. [default: False]
    --app_daemon_stdout=TWITTER_COMMON_APP_DAEMON_STDOUT
                        Direct this app's stdout to this file if daemonized .
                        [default: /dev/null]
    --app_profiling     Run profiler on the code while it runs.  Note this can
                        cause slowdowns. [default: False]
    --app_ignore_rc_file
                        Ignore default arguments from the rc file. [default:
                        False]
    --app_pidfile=TWITTER_COMMON_APP_PIDFILE
                        The pidfile to use if --app_daemonize is specified.
                        [default: None]
```

Or we can simply execute it as intended:

```console
$ dist/hello_world.pex
Hello world!
```


# Environment manipulation with `pants py` #

We've only discussed so far the "pants build" command.  There's also a
dedicated "py" command that allows you to manipulate the environments
described by `python_binary` and `python_library` targets, such as drop into
an interpreter with the environment set up for you.

## `pants py` semantics ##

The default behavior of `pants py <target>` is the following:

1. For `python_binary` targets, build the environment and execute the target
2. For one or more `python_library` targets, build the environment that is the transitive closure of all targets and drop into an interpreter.
3. For a combination of `python_binary` and `python_library` targets, build the transitive closure of all targets and execute the first binary target.


## external dependencies ##

Let's take `src/python/twitter/tutorial/BUILD` and split out the dependencies from
our `hello_world` target into `hello_world_lib` and add dependencies upon
[Tornado](http://github.com/facebook/tornado) and [psutil](http://code.google.com/p/psutil/).

```python
python_binary(
  name = "hello_world",
  source = "hello_world.py",
  dependencies = [
    pants(":hello_world_lib")
  ]
)

python_library(
  name = "hello_world_lib",
  dependencies = [
    pants("src/python/twitter/common/app"),
    python_requirement("tornado"),
    python_requirement("psutil"),
  ]
)
```

This uses the `python_requirement` target which can refer to any string in `pkg_resources.Requirement` format as
recognized by tools such as `easy_install` and `pip` as described above.

Now that we've created a library-only target `src/python/twitter/tutorial:hello_world_lib`, let's drop
into it using `pants py` with verbosity turned on so that we can see what's
going on in the background:

```console
$ PANTS_VERBOSE=1 ./pants py src/python/twitter/tutorial:hello_world_lib
Build operating on target: PythonLibrary(src/python/twitter/tutorial/BUILD:hello_world_lib)
  Resolver: Calling environment super => 0.019ms
Building PythonBinary PythonLibrary(src/python/twitter/tutorial/BUILD:hello_world_lib):
  Dumping library: PythonLibrary(src/python/twitter/tutorial/BUILD:hello_world_lib) [relative module: ]
  Dumping library: PythonLibrary(src/python/twitter/common/app/BUILD:app) [relative module: ]
  Dumping library: PythonLibrary(src/python/twitter/common/dirutil/BUILD:dirutil) [relative module: ]
  Dumping library: PythonLibrary(src/python/twitter/common/lang/BUILD:lang) [relative module: ]
  Dumping library: PythonLibrary(src/python/twitter/common/options/BUILD:options) [relative module: ]
  Dumping library: PythonLibrary(src/python/twitter/common/util/BUILD:util) [relative module: ]
  Dumping library: PythonLibrary(src/python/twitter/common/app/modules/BUILD:modules) [relative module: ]
  Dumping requirement: tornado
  Dumping requirement: psutil
  Resolver: Calling environment super => 0.029ms
  Resolver: Activating cache /private/tmp/wickman-commons/3rdparty/python => 356.432ms
  Resolver: Resolved tornado => 357.219ms
  Resolver: Activating cache /private/tmp/wickman-commons/.pants.d/.python.install.cache => 41.117ms
  Resolver: Fetching psutil => 10144.264ms
  Resolver: Building psutil => 1794.474ms
  Resolver: Distilling psutil => 224.896ms
  Resolver: Constructing distribution psutil => 2.855ms
  Resolver: Resolved psutil => 12210.066ms
  Dumping distribution: .../tornado-2.2-py2.6.egg
  Dumping distribution: .../psutil-0.4.1-py2.6-macosx-10.4-x86_64.egg
Python 2.6.7 (r267:88850, Aug 31 2011, 15:49:05)
[GCC 4.2.1 (Apple Inc. build 5664)] on darwin
Type "help", "copyright", "credits" or "license" for more information.
(InteractiveConsole)
>>>
```

In the background, `pants` used cached version of `tornado` but fetched
`psutil` from pypi and any necessary transitive dependencies (none in this
case) and built a platform-specific version for us.

You can convince yourself that the environment contains all the dependencies
by inspecting `sys.path` and importing libraries as you desire:

```console
>>> import psutil
>>> help(psutil)
>>> from twitter.common import app
>>> help(app)
```

It should be stressed that *dependencies built by Pants are never installed globally*.
These dependencies only exist for the duration of the Python interpreter forked by Pants.


## Running an application using `pants py` ##

Let us turn our `hello_world.py` into a basic `top` application using `tornado`:

```python
from twitter.common import app

import psutil
import tornado.ioloop
import tornado.web

class MainHandler(tornado.web.RequestHandler):
  def get(self):
    self.write('<pre>Running pids:\n%s</pre>' % '\n'.join(map(str, psutil.get_pid_list())))

def main():
  application = tornado.web.Application([
    (r"/", MainHandler)
  ])
  application.listen(8888)
  tornado.ioloop.IOLoop.instance().start()

app.main()
```

We have now split our application into two parts: the `hello_world` binary
target and the `hello_world_lib` library target.  If we run `pants py
src/python/twitter/tutorial:hello_world_lib`, the default behavior is to
drop into an interpreter.

If we run `pants py src/python/twitter/tutorial:hello_world`, the default behavior is to run
the binary target pointed to by `hello_world`:

```console
$ ./pants py src/python/twitter/tutorial:hello_world
```

Then point your browser to [localhost:8888](http://localhost:8888)


## pants py --pex ##

There is also a `--pex` option to pants py that allows you to build a PEX
file from a union of python_library targets that does not necessarily have a
`python_binary` target defined for it.  Since there is no entry point
specified, the resulting .pex file just behaves like a Python interpreter,
but with the sys.path bootstrapped for you:

```console
$ ./pants py --pex src/python/twitter/tutorial:hello_world_lib
Build operating on target: PythonLibrary(src/python/twitter/tutorial/BUILD:hello_world_lib)
Wrote /private/tmp/wickman-commons/dist/hello_world_lib.pex

$ ls -la dist/hello_world_lib.pex
-rwxr-xr-x  1 wickman  wheel  1404174 Apr 10 13:00 dist/hello_world_lib.pex
```

Now if you use dist/hello_world_lib.pex, since it has no entry point, it will drop you into an interpreter:

```console
$ dist/hello_world_lib.pex
Python 2.6.7 (r267:88850, Aug 31 2011, 15:49:05)
[GCC 4.2.1 (Apple Inc. build 5664)] on darwin
Type "help", "copyright", "credits" or "license" for more information.
(InteractiveConsole)
>>> import tornado
```

As mentioned before, it's like a single-file lightweight alternative to a
virtualenv.  We can even use it to run our `hello_world.py` application:

```console
$ dist/hello_world_lib.pex src/python/twitter/tutorial/hello_world.py
```

This can be an incredibly powerful and lightweight way to manage and deploy
virtual environments without using `virtualenv`.


## PEX file as interpreter ##

As mentioned above, PEX files without default entry points behave like Python interpreters that
carry their dependencies with them.  For example, let's create a target that
provides a Fabric dependency within `src/python/twitter/tutorial/BUILD`:

```python
python_library(
  name = 'fabric',
  dependencies = [
    python_requirement('Fabric')
  ]
)
```

And let's build a fabric PEX file:

```console
$ ./pants py --pex src/python/twitter/tutorial:fabric
Build operating on target: PythonLibrary(src/python/twitter/tutorial/BUILD:fabric)
Wrote /private/tmp/wickman-commons/dist/fabric.pex
```

By default it does nothing more than drop us into an interpreter:

```console
$ dist/fabric.pex
Python 2.6.7 (r267:88850, Aug 31 2011, 15:49:05)
[GCC 4.2.1 (Apple Inc. build 5664)] on darwin
Type "help", "copyright", "credits" or "license" for more information.
(InteractiveConsole)
>>>
```

But suppose we have a local script that depends upon Fabric, `fabric_hello_world.py`:

```python
from fabric.api import *

def main():
  local('echo hello world')

if __name__ == '__main__':
  main()
```

We can now use `fabric.pex` as if it were a Python interpreter but with
fabric available in its environment.  Note that fabric has never been
installed globally in any site-packages anywhere.  It is just bundled inside
of fabric.pex:

```console
$ dist/fabric.pex fabric_hello_world.py
[localhost] local: echo hello world
hello world
```


## python_binary entry_point ##

An advanced feature of `python_binary` targets, you may in addition specify
direct entry points into PEX files rather than a source file.  For example,
if we wanted to build an a la carte `fab` wrapper for fabric:

```python
python_binary(name = "fab",
  entry_point = "fabric.main:main",
  dependencies = [
    python_requirement("fabric"),
  ]
)
```

We build:

```console
$ ./pants src/python/twitter/tutorial:fab
Build operating on targets: OrderedSet([PythonBinary(src/python/twitter/tutorial/BUILD:fab)])
Building PythonBinary PythonBinary(src/python/twitter/tutorial/BUILD:fab):
Wrote /private/tmp/wickman-commons/dist/fab.pex
```

And now `dist/fab.pex` behaves like a standalone `fab` binary:

```console
$ dist/fab.pex -h
Usage: fab [options] <command>[:arg1,arg2=val2,host=foo,hosts='h1;h2',...] ...

Options:
  -h, --help            show this help message and exit
  -d NAME, --display=NAME
                        print detailed info about command NAME
  -F FORMAT, --list-format=FORMAT
                        formats --list, choices: short, normal, nested
  -l, --list            print list of possible commands and exit
  --set=KEY=VALUE,...   comma separated KEY=VALUE pairs to set Fab env vars
  --shortlist           alias for -F short --list
  -V, --version         show program's version number and exit
  -a, --no_agent        don't use the running SSH agent
  -A, --forward-agent   forward local agent to remote end
  --abort-on-prompts    abort instead of prompting (for password, host, etc)

  ...
```

Pants also has excellent support for JVM-based builds and can do similar
things like resolving external JARs and packaging them as standalone
environments with default entry points.


# Manipulating PEX behavior with environment variables #

Given a PEX file, it is possible to alter its default behavior during invocation.

## PEX_INTERPRETER=1 ##

If you have a PEX file with a prescribed executable source or `entry_point` specified, it may still
occasionally be useful to drop into an interpreter with the environment bootstrapped.  If you
set `PEX_INTERPRETER=1` in your environment, the PEX bootstrapper will skip any execution and instead
launch an interactive interpreter session.


## PEX_VERBOSE=1 ##

If your environment is failing to bootstrap or simply bootstrapping very slowly, it can be useful to
set `PEX_VERBOSE=1` in your environment to get debugging output printed to the console.  Debugging output
includes:

1. Fetched dependencies
2. Built dependencies
3. Activated dependencies
4. Packages scrubbed out of `sys.path`
5. The `sys.path` used to launch the interpreter

## PEX_MODULE=entry_point ##

If you have a PEX file without a prescribed entry point, or want to change
the `entry_point` for the duration of a single invocation, you can set
`PEX_MODULE=entry_point` using the same format as described in the
`python_binary` Pants target.

This can be a useful tool for bundling up a number of packages together and
being able to use a single file to execute scripts from each of them.

Another common pattern is to link `pytest` into your PEX file, and run
`PEX_MODULE=pytest my_pex.pex tests/*.py` to run your test suite in its
isolated environment.

## PEX_COVERAGE ##

There is nascent support for performing code coverage within PEX files by
setting `PEX_COVERAGE=<suffix>`.  By default the coverage files will be written
into the current working directory with the file pattern `.coverage.<suffix>`.  This
requires that the `coverage` Python module has been linked into your PEX.

You can then combine the coverage files by running `PEX_MODULE=coverage
my_pex.pex .coverage.suffix*` and run a report using `PEX_MODULE=coverage
my_pex.pex report`.  Since PEX files are just zip files, `coverage` is able
to understand and extract source and line numbers from them in order to
produce coverage reports.


# How PEX files work #

## the utility of zipimport and `__main__.py` ##

As an aside, in Python, you may not know that you can import code from directories:

```console
$ mkdir -p foo
$ touch foo/__init__.py
$ echo "print 'spam'" > foo/bar.py
$ python -c 'import foo.bar'
spam
```

All that is necessary is the presence of `__init__.py` to signal to the importer that we
are dealing with a package.  Similarly, a directory can be made "executable":

```console
$ echo "print 'i like flowers'" > foo/__main__.py
$ python foo
i like flowers
```

And because the `zipimport` module now provides a default import hook for
Pythons >= 2.4, if the Python import framework sees a zip file, with the
inclusion of a proper `__init__.py`, it can be treated similarly to a
directory.  But since a directory can be executable, if we just drop a
`__main__.py` into a zip file, it suddenly becomes executable:

```console
$ pushd foo && zip /tmp/flower.zip __main__.py && popd
/tmp/foo /tmp
  adding: __main__.py (stored 0%)
/tmp
$ python flower.zip
i like flowers
```

And since zip files don't actually start until the zip magic number, you can
embed arbitrary strings at the beginning of them and they're still valid
zips.  Hence simple PEX files are born:

```console
$ echo '#!/usr/bin/env python2.6' > flower.pex && cat flower.zip >> flower.pex
$ chmod +x flower.pex
$ ./flower.pex
i like flowers
```

Remember `pants.pex`?

```console
$ unzip -l pants.pex | tail -2
warning [pants.pex]:  25 extra bytes at beginning or within zipfile
  (attempting to process anyway)
 --------                   -------
  7900812                   543 files

$ head -c 25 pants.pex
#!/usr/bin/env python2.6
```

## PEX `__main__.py` ##

The `__main__.py` in a real PEX file is somewhat special:

```python
import os
import sys

__entry_point__ = None
if '__file__' in locals() and __file__ is not None:
  __entry_point__ = os.path.dirname(__file__)
elif '__loader__' in locals():
  from pkgutil import ImpLoader
  if hasattr(__loader__, 'archive'):
    __entry_point__ = __loader__.archive
  elif isinstance(__loader__, ImpLoader):
    __entry_point__ = os.path.dirname(__loader__.get_filename())

if __entry_point__ is None:
  sys.stderr.write('Could not launch python executable!\n')
  sys.exit(2)

sys.path.insert(0, os.path.join(__entry_point__, '.bootstrap'))

from twitter.common.python.importer import monkeypatch
monkeypatch()
del monkeypatch

from twitter.common.python.pex import PEX
PEX(__entry_point__).execute()
```

`PEX` is just a class that manages requirements (often embedded within PEX
files as egg distributions in the `.deps` directory) and autoimports them
into the `sys.path`, then executes a prescribed entry point.

If you read the code closely, you'll notice that it relies upon monkeypatching
`zipimport`.  Inside the `twitter.common.python` library we've provided a recursive
zip importer derived from Google's [pure Python zipimport](http://code.google.com/appengine/articles/django10_zipimport.html)
module that allows for depending upon eggs within eggs or zips (and so forth)
so that PEX files need not extract egg dependencies to disk a priori.  This even
extends to C extensions (.so and .dylib files) which are written to disk long
enough to be dlopened before being unlinked.

Strictly speaking this monkeypatching is not necessary and we may consider
making that optional.



# Advanced Pants/PEX features #

TODO: converting python_library targets to eggs

TODO: auto dependency resolution from within PEX files

TODO: dynamically self-updating PEX files

TODO: tailoring your dependency resolution environment with pants.ini, including local cheeseshop mirrors
