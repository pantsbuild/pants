Scala Projects with Pants
=========================

Pants' Scala tooling has much in common with its Java tooling. (That's
not surprising; Scala compiles to run on the JVM.) If you already know
[[how to use Pants to build JVM code|pants('examples/src/java/org/pantsbuild/example:readme')]]
 and you know that
`BUILD` files can have <a xref="bdict_scala_library">`scala_library`</a> targets,
then you're set to use Pants with Scala code.

Hello Pants Scala
-----------------

The sample code
[examples/src/scala/org/pantsbuild/example/hello/welcome/](https://github.com/pantsbuild/pants/blob/master/examples/src/scala/org/pantsbuild/example/hello/welcome/)
shows how you can define a library of Scala code.

Its `BUILD` file looks like that for a Java library, but contains a
`scala_library` target with `.scala` sources:

!inc[start-at=scala_library](hello/welcome/BUILD)

There's a sample test in
[examples/tests/scala/org/pantsbuild/example/hello/welcome](https://github.com/pantsbuild/pants/tree/master/examples/tests/scala/org/pantsbuild/example/hello/welcome).
It's a <a xref="bdict_junit_tests">`junit_tests`</a> with `.scala` sources.
(You might have thought JUnit was only for Java testing, but it also works great
for Scala.)

!inc[start-at=junit_tests](../../../../../tests/scala/org/pantsbuild/example/hello/welcome/BUILD)

Scala/Java Circular Dependencies
--------------------------------

Scala code and Java code can depend on each other. As long as the dependencies aren't circular,
`scala_library` targets can depend on `java_library` targets and vice versa. If the dependencies
*are* circular, you can set up targets to compile all of this code together. Assuming your `*.java`
and `*scala` files are in separate directories, you can:

-   a `java_library` whose `sources` param is the `*.java` files; one of its
    dependencies should be...
-   a `scala_library` whose `sources` param is the `*.scala` files and
    whose `java_sources` is the above `java_library`.

Do not put the `java_library` in the `scala_library`'s `dependencies` or Pants will error out in its
circular dependencies check. Instead, put the `java_library` in `java_sources` to work around this
check.

The [`scala_with_java_sources`](https://github.com/pantsbuild/pants/tree/master/examples/src/scala/org/pantsbuild/example/scala_with_java_sources)
example shows how this can work:

!inc[start-at=scala_library](scala_with_java_sources/BUILD)

The referred-to
[`java_sources`](https://github.com/pantsbuild/pants/tree/master/examples/src/java/org/pantsbuild/example/java_sources/BUILD)
`java_library` has this `java_library` in its dependencies:

!inc[start-at=java_library](../../../../java/org/pantsbuild/example/java_sources/BUILD)

(If your circularly-referencing `*.scala` and `*.java` files are in the *same* directory, you don't
need separate `java_library` and `scala_library` targets. Instead, use
`scala_library(sources=globs('*.scala', '*.java'),...)`.)

Scala Console
-------------

To bring up Scala's interactive console, use Pants'
<a xref="oref_goal_repl">`repl`</a> goal.
In the resulting console, you can `import` code from the Pants invocation's
targets and their dependencies.

    $ ./pants repl examples/src/scala/org/pantsbuild/example/hello/welcome
       ...much build output...
    15:08:13 00:11   [resources]
    15:08:13 00:11     [prepare]
                       Invalidated 1 target containing 1 payload file.
    15:08:13 00:11   [repl]
    15:08:13 00:11     [python-repl]
    15:08:13 00:11     [scala-repl]
    15:08:13 00:11       [bootstrap-scala-repl]
    Welcome to Scala version 2.10.4 (Java HotSpot(TM) 64-Bit Server VM, Java 1.7.0_60).
    Type in expressions to have them evaluated.
    Type :help for more information.

    scala> import org.pantsbuild.example.hello.welcome
    import org.pantsbuild.example.hello.welcome

    scala> val folks = List("Abel", "Baker", "Charlie", "Delta")
    folks: List[java.lang.String] = List(Abel, Baker, Charlie, Delta)

    scala> org.pantsbuild.example.hello.welcome.WelcomeEverybody(folks)
    res0: Seq[String] = List(Hello, Abel!, Hello, Baker!, Hello, Charlie!, Hello, Delta!)

    scala> exit
    warning: there were 1 deprecation warnings; re-run with -deprecation for details

                   Waiting for background workers to finish.
                   SUCCESS

    $

Pants' `repl` goal works with JVM targets. (It also works with Python targets, but that uses a
Python console instead.)
