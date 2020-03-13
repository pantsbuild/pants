
## Problem

You want to compile and/or run different test or binary targets using different JVMs.

Or, you need to specify command-line options globally for the JVM on a per-JVM version basis. For
example, using `--add-opens` flags, but only when running on JVMs that support it.

## Solution

In your global configuration (most likely `pants.toml`), declare JVM platforms using the
`jvm-platform` configuration section to define the set of available platforms.

On targets, add the named argument `runtime_platform` set to the name of one of the platforms
defined in `jvm-platform`. That will tell pants to use that platform when running that target in a
 JVM.

    runtime_platform="java8",

To compile with a specific platform, set the `platform` on the target.

    platform="java8",

To set the defaults for `platform` and `runtime_platform`, add `default_platform` and
`default_runtime_platform` to your global config.

## Discussion

Here are the different configurations that you can set when defining a JVM platform in your global
configuration.

For compile time configuration, there are three main attributes, `source`, `target` and `args`.
* `source` and `target` map directly to the javac arguments of the same name, though they accept
more aliases than javac. Up to JDK 8, you can use either `1.X` or `X`. For 9 and up, you can't
include the `1.`.
 * `args`, allows the platform to specify additional, global to that platform, compile arguments.

For runtime configuration, `target`, `strict` and `jvm_options` are used. `target` is used to
determine the minimum version of the JVM to use. `strict` forces the JVM used to be exactly the
`target` version. `jvm_options` is used by some tasks to allow platforms to specify platform
specific JVM options. These can make transitions between JVM versions smoother by allowing
compatibility options to be provided globally.

An example pants.toml config might look like this:

    [jvm-platform]
    default_platform: java8
    default_runtime_platform: java10
    platforms =
    """
     {
        'java8': { 'source': '8', 'target': '8', 'args': [] },
        'java10': {'source': '10', 'target': '10', 'args': [],
                   'strict': True,
                   'jvm_options': [
                       # --add-opens is a 9+ flag, that doesn't work with 8
                       '--add-opens=java.base/java.lang.reflect=ALL-UNNAMED'
                   ] },
      }
   """


## See Also

* [[Specify JVM Options|pants('src/docs/common_tasks:jvm_options')]]
* [[Run a Binary Target|pants('src/docs/common_tasks:run')]]
