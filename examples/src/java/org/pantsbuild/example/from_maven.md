Pants for Maven Experts
=======================

If you're used to Maven and learning Pants, you're part of a growing
crowd. Here are some things that helped other folks come up to speed.

The good news is that Pants and Maven are pretty similar. Both tools use
several configuration-snippet files near in source code directories to
specify how to build those directories' source code. Both tools use the
configuration-snippet files to build up a model of your source code,
then execute tasks in a lifecycle over that model. Pants targets tend to
be finer-grained than Maven's projects; but if you use subprojects in
Maven, Pants targets might feel familiar. (If you're converting Maven
`pom.xml`s to `BUILD` files, <a pantsref="setup_mvn2pants">some scripts written by others who
have done the same</a> can give you a head start.)
Both Maven and Pants expect code to be laid out in directories in a consistent way. If you're used
to Maven's commands, many of Pants' goals will feel eerily familiar.

Pants uses Ivy to manage artifact fetching and publishing; Ivy's
behavior here is pretty similar to Maven.

Three Pants features that especially confuse Maven experts as they move
to pants are

-   Pants has a first-class mechanism for targets depending on other
    targets on the local file system
-   Pants targets do not specify version numbers; versions are only
    determined during release
-   BUILD files are python code that pants evaluates dynamically.

The first two points are a significant departure from Maven's handling
of inter-project dependencies. The last point isn't necessary for
understanding how to read and write most BUILD files, but is helpful to
be aware of.

Folks switching a Maven-built codebase to Pants often encounter another
source of confusion: they uncover lurking jar-dependency version
conflicts. JVM projects can inadvertently end up relying on classpath
order for correctness; any two build tools will order their classpaths
differently. If your project depends on two versions of the same jar
(all too easy to do with transitive dependencies), then your Maven build
chose one version, but Pants might end up choosing another: Pants is
likely to generate a differently-ordered `CLASSPATH` than Maven did. You
can fix these, making your build configuration more robust along the
way; see
[[JVM 3rdparty Pattern|pants('examples/src/java/org/pantsbuild/example:3rdparty_jvm')]]
for advice.

Pants Equivalents
-----------------

`exec:java` run a binary<br>
`run`

`-Xdebug` run a binary in the debugger<br>
`run.jvm --jvm-debug`

`-Dtest=com.foo.BarSpec -Dmaven.surefire.debug=true test` run one test in the debugger<br>
`test.junit --jvm-debug --test=com.foo.BarSpec`

Depending on Source, not Jars
-----------------------------

Pants arose in an environment of a big multi-project repo. Several teams
contributed code to the same source tree; projects depended on each
other. Getting those dependencies to work with Maven was tricky. As the
number of engineers grew, it wasn't so easy to have one team ask another
team to release a new jar. Using snapshot dependencies mostly worked,
but it wasn't always clear what needed rebuilding when pulling fresh
code from origin; if you weren't sure and didn't want to investigate,
the safe thing was to rebuild everything your project depended upon.
Alas, for a big tree of Scala code, that might take 45 minutes.

Pants has a first-class concept of "depend on whatever version of this
project is defined on disk," and caches targets based on their
fingerprints (i.e. SHAs of the contents of the files and command line
options used to build the target). When code changes (e.g., after a git
pull), pants recompiles only those targets whose source files have
differing contents.

