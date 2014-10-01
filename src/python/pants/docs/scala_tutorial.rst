#########################
Scala Projects with Pants
#########################

Pants' Scala tooling has much in common with its Java tooling. (That's not
surprising; Scala compiles to run on the JVM.) If you already know
:doc:`how to use Pants to build JVM code <JVMProjects>`, and you know
that ``BUILD`` files can have ``scala_library``, you're set to use Pants
with Scala code.

*****************
Hello Pants Scala
*****************

The sample code `examples/src/scala/com/pants/example/hello/welcome/
<https://github.com/pantsbuild/pants/blob/master/examples/src/scala/com/pants/example/hello/welcome/>`_
shows how you can define a library of Scala code.

Its ``BUILD`` file looks like that for a Java library, but contains
a ``scala_library`` target with ``.scala`` sources:

.. literalinclude:: ../../../../examples/src/scala/com/pants/example/hello/welcome/BUILD
   :start-after: Seq-friendly wrapper

There's a sample test in
`examples/tests/scala/com/pants/example/hello/welcome
<https://github.com/pantsbuild/pants/tree/master/examples/tests/scala/com/pants/example/hello/welcome>`_.
It's a ``junit_tests`` with ``.scala`` sources.
(Pants also has a :ref:`scala_specs <bdict_scala_specs>` target type for testing
with Specs.)

.. literalinclude:: ../../../../examples/tests/scala/com/pants/example/hello/welcome/BUILD
   :start-after: test it anyhow

********************************
Scala/Java Circular Dependencies
********************************

Scala code and Java code can depend on each other. As long as the dependencies
aren't circular, ``scala_library`` targets can depend on
``java_library`` targets and vice versa. If the dependencies
*are* circular, you can set up targets to compile all of this code together:

* a ``java_library`` whose ``sources`` param is the ``*.java`` files.
* a ``scala_library`` whose ``sources`` param is the ``*.scala`` files
  and whose ``java_sources`` is the above ``java_library``.

TODO: should the sources have the same ``package``? That was true
in the sample space of 1 example I looked at.

*************
Scala Console
*************

To bring up Scala's interactive console, use Pants ``repl`` goal.
In the resulting console, you can ``import`` code from the Pants invocation's
targets and their dependencies. ::

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

Pants' ``repl`` goal works with JVM targets.
