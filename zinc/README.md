Zinc
====

Zinc is a stand-alone version of [sbt]'s incremental compiler meant to be run in nailgun. This version is derived from

github.com/twitter-forks/zinc.git:

Add 'zinc/' from commit '609ee645c61dc7970b008c25c7a7dd94c21be865'

git-subtree-dir: zinc
git-subtree-mainline: 85fd6a4a0560fd4ab624ab12345e1087b51ce2f6
git-subtree-split: 609ee645c61dc7970b008c25c7a7dd94c21be865


Build
-----

Zinc is built using pants:

    ./pants test zinc:

To build a jar use:

    ./pants binary.dup --excludes="['rootdoc.txt']" zinc:

To consume a jar, change the zinc target in BUILD.tools. To force pants to re-resolve
and re-shade the artifact, use a new `rev` whenever the artifact has changed.

    jar_library(name = 'zinc',
                jars = [
                  jar(org = 'org.pantsbuild', name = 'zinc', rev = ???,
                      url = 'file:///Users/user/pants/dist/zinc.jar'),
                ])


Options
-------

To get information about options

    ./pants run zinc: -- -help

### Compile

As for `scalac` the main options for compiling are `-classpath` for specifying
the classpath elements, and `-d` for selecting the output directory. Anything
passed on the command-line that is not an option is considered to be a source
file.

### Scala

Zinc needs to locate the Scala compiler jar, Scala library jar, and any extra
Scala jars (like Scala reflect). There are three alternative ways to specify the
Scala jars.

Using `-scala-home` point to the base directory of a Scala distribution (which
needs to contain a `lib` directory with the Scala jars).

Using `-scala-path` the compiler, library, and any extra jars (like scala
reflect) can be listed directly as a path.

Using `-scala-library` to directly specify the Scala library, `-scala-compiler`
to specify the Scala compiler, and `-scala-extra` to specify any extra Scala
jars.

If no options are passed to locate a version of Scala then Scala 2.9.2 is used
by default (which is bundled with zinc).

To pass options to scalac simply prefix with `-S`. For example, deprecation
warnings can be enabled with `-S-deprecation`. For multi-part options add the
`-S` prefix to all parts. For example, the sourcepath option can be specified
with `-S-sourcepath -S/the/source/path`.

### Java

To select a different `javac` to compile Java sources, use the `-java-home`
option. To pass options to javac, prefix with `-C`.

If mixed Java and Scala sources are being compiled then the compile order can be
specified with `-compile-order`, where the available orders are `Mixed`,
`JavaThenScala`, or `ScalaThenJava`. The default order is `Mixed`.

If only Java sources are being compiled then the `-java-only` option can be
added to avoid the Scala library jar being automatically added to the classpath.

### Nailed

Zinc assumes that it will be run in Nailgun. Running with Nailgun provides
zinc as a server, communicating commands via a client, keeping cached compilers
in a warm running JVM and avoiding startup and load times.

[Nailgun]: http://www.martiansoftware.com/nailgun

### Logging

The log level can be set directly with `-log-level debug|info|warn|error`. Or to
set to debug use `-debug`. To silence all logging use `-quiet`.

### Analysis

The analysis used to determine which files to incrementally recompile is stored
in a file. The default location for the analysis cache is relative to the output
directory. To specify a different location for the analysis cache use the
`-analysis-cache` option. When compiling multiple projects, and the analysis
cache is not at the default location, then a mapping from output directory to
cache file for any upstreams projects should also be provided with the
`-analysis-map` option.

### Incremental Compiler

There are options for configuring the incremental compiler. One useful option is
`-transactional`, which will restore the previous class files on compilation
failure. This allows fixes to be made before retrying incremental compilation,
rather than forcing recompilation of larger parts of the source tree due to the
error and deleted class files.

See `zinc -help` for information about all options.


License
-------

Copyright 2012 Typesafe, Inc.

Licensed under the [Apache License, Version 2.0][apache2] (the "License"); you
may not use this software except in compliance with the License. You may obtain
a copy of the License at:

[http://www.apache.org/licenses/LICENSE-2.0][apache2]

Unless required by applicable law or agreed to in writing, software distributed
under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.

[apache2]: http://www.apache.org/licenses/LICENSE-2.0
