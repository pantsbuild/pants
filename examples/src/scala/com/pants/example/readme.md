Scala Projects with Pants
=========================

Pants' Scala tooling has much in common with its Java tooling. (That's
not surprising; Scala compiles to run on the JVM.) If you already know
[[how to use Pants to build JVM code|pants('examples/src/java/com/pants/examples:readme')]],
 and you know that
`BUILD` files can have <a xref="bdict_scala_library">`scala_library`</a>,
you're set to use Pants with Scala code.

Hello Pants Scala
-----------------

The sample code
[examples/src/scala/com/pants/example/hello/welcome/](https://github.com/pantsbuild/pants/blob/master/examples/src/scala/com/pants/example/hello/welcome/)
shows how you can define a library of Scala code.

Its `BUILD` file looks like that for a Java library, but contains a
`scala_library` target with `.scala` sources:

!inc[start-after=Seq-friendly wrapper](hello/welcome/BUILD)

There's a sample test in
[examples/tests/scala/com/pants/example/hello/welcome](https://github.com/pantsbuild/pants/tree/master/examples/tests/scala/com/pants/example/hello/welcome).
It's a <a xref="bdict_junit_tests">`junit_tests`</a> with `.scala` sources.
(Pants also has a
<a xref="bdict_scala_specs">`scala_specs`</a> target type for testing with
Specs.)

!inc[start-after=test it anyhow](../../../../../tests/scala/com/pants/example/hello/welcome/BUILD)

Scala/Java Circular Dependencies
--------------------------------

Scala code and Java code can depend on each other. As long as the
dependencies aren't circular, `scala_library` targets can depend on
`java_library` targets and vice versa. If the dependencies *are*
circular, you can set up targets to compile all of this code together:

-   a `java_library` whose `sources` param is the `*.java` files.
-   a `scala_library` whose `sources` param is the `*.scala` files and
    whose `java_sources` is the above `java_library`.

The [`scala_with_java_sources`](https://github.com/pantsbuild/pants/tree/master/examples/src/scala/com/pants/example/scala_with_java_sources)
example shows how this can work:

!inc[start-after=LICENSE](scala_with_java_sources/BUILD)

Scala Console
-------------

To bring up Scala's interactive console, use Pants
<a xref="gref_goal_repl">`repl`</a> goal.
In the resulting console, you can `import` code from the Pants invocation's
targets and their dependencies.

    $ ./pants goal repl examples/src/scala/com/pants/example/hello/welcome
       ...much build output...
    15:08:13 00:11   [resources]
    15:08:13 00:11     [prepare]
                       Invalidated 1 target containing 1 payload file.
    15:08:13 00:11   [repl]
    15:08:13 00:11     [python-repl]
    15:08:13 00:11     [scala-repl]
    15:08:13 00:11       [bootstrap-scala-repl]
    Welcome to Scala version 2.9.3 (Java HotSpot(TM) 64-Bit Server VM, Java 1.7.0_60).
    Type in expressions to have them evaluated.
    Type :help for more information.

    scala> import com.pants.example.hello.welcome
    import com.pants.example.hello.welcome

    scala> val folks = List("Abel", "Baker", "Charlie", "Delta")
    folks: List[java.lang.String] = List(Abel, Baker, Charlie, Delta)

    scala> com.pants.example.hello.welcome.WelcomeEverybody(folks)
    res0: Seq[String] = List(Hello, Abel!, Hello, Baker!, Hello, Charlie!, Hello, Delta!)

    scala> exit
    warning: there were 1 deprecation warnings; re-run with -deprecation for details

                   Waiting for background workers to finish.
                   SUCCESS

    $

Pants' `repl` goal works with JVM targets. (It also works with Python targets, but that uses a
Python console instead.)