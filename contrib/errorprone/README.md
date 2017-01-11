# Pants plugin for Error Prone

The Error Prone plugin runs static analysis on Java source files and looks for various
[bug patterns](http://errorprone.info/bugpatterns) not reported by the standard javac compiler.

A full description of Error Prone can be found on the [Error Prone web page](http://errorprone.info/).

One notable difference between this plugin and other Error Prone integrations is this plugin does not replace the javac executable used for compilation.  Instead, it runs the Error Prone javac as a separate task after regular javac compilation is run.  This is obviously slower than running the compiler once but it avoids a trickier integration with the Pants incremental compilation tool [Zinc](https://github.com/sbt/zinc).


## Installation

Error Prone support is provided by a plugin distributed to [pypi]
(https://pypi.python.org/pypi/pantsbuild.pants.contrib.errorprone).
Assuming you have already [installed pants](http://www.pantsbuild.org/install.html), you'll need to
add the Error Prone plugin in your `pants.ini`, like so:
```ini
[GLOBAL]
pants_version: 1.3.0

plugins: [
    'pantsbuild.pants.contrib.errorprone==%(pants_version)s',
  ]
```

The version of Error Prone used by the plugin requires Java 8 to run.  If you want to run Error Prone with Java 7 you will need to use version 2.0.5 or earlier. Using Java 7 may require changes to the bootclasspath to override certain classes from `rt.jar`.  See [this github issue](https://github.com/google/error-prone/issues/287) for more details.

You can override the version of Error Prone by adding the following to the `BUILD.tools` file
```ini
# Override the default version of Error Prone shipped with Pants
jar_library(name = 'errorprone',
  jars = [
    jar(org = 'com.google.errorprone', name = 'error_prone_core', rev = '2.0.5'),
  ],
)
```

## Running

When you run `./pants compile` Error Prone is executed after the compile step and will run on any targets that contain java files.

```
./pants compile <target>
...
      00:07:42 00:00     [compile]
      00:07:42 00:00     [zinc]
      00:07:42 00:00     [jvm-dep-check]
      00:07:42 00:00     [checkstyle]
      00:07:42 00:00     [errorprone]
                         Invalidated 7 targets.
      00:07:42 00:00       [errorprone]
...
```

## Options

You can exclude targets with `--compile-errorprone-exclude-patterns` and globally suppress specific Error Prone checks with `--compile-errorprone-command-line-options`.

Here are example `pants.ini` settings that exclude several test targets and disable the `DefaultCharset` bug pattern.

```ini
[compile.errorprone]
command_line_options: [
    # See http://errorprone.info/bugpatterns for all patterns
    '-Xep:DefaultCharset:OFF'
  ]
exclude_patterns: [
    'tests/java/org/pantsbuild/tools/junit/.*',
    'testprojects/src/java/org/pantsbuild/testproject/annotation/main:main'
  ]
```
