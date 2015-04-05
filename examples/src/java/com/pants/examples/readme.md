JVM Projects with Pants
=======================

Assuming you know the basic
[[Pants concepts|pants('src/docs:first_concepts')]]
and have gone through the
[[first Tutorial|pants('src/docs:first_tutorial')]],
you've made a great start towards
using Pants to work with Java and Scala code. This page goes into some
of the details.

If you are accustomed to the Maven tool and contemplating moving to
Pants, you are not alone;
[[Pants for Maven Experts|pants('examples/src/java/com/pants/examples:from_maven')]]
has some advice.

Relevant Goals and Targets
--------------------------

When working with JVM languages, the following goals and targets are
especially relevant.

**Deployable Bundle** *Runnable Binary, optionally with non-JVM files*

> Deployable bundles are directories, optionally archived, that contain
> all files necessary to run the application. The `bundle` goal is used
> to create these deployable bundles from either `jvm_binary` or
> `jvm_app` targets.
>
> Bundling a `jvm_binary` target is appropriate when your application is
> entirely jar-based; that is, it's entirely class files and resources
> packaged inside the jars themselves. If your application requires
> "extra stuff" (e.g.: start scripts, config files) use a `jvm_app`
> which allows you to include files in the bundle directory that
> supplement the binary jar and its dependencies. You can learn
> more about <a pantsref="jvm_bundles">bundles</a>

**Runnable Binary**

> On its own, a `jvm_binary` BUILD target describes an executable `.jar`
> (something you can run with `java -jar`). The jar is described as
> executable because it contains a manifest file that specifies the main
> class as well as classpath for all dependencies. If your program
> contains only jars (and resources packaged in those jars), this is all
> you need to run the binary. Use `./pants binary` to compile its
> code; `./pants run` to run it "in place".

**Importable Code**

> `java_library` BUILD targets make Java source code `import`-able. The
> rule of thumb is that each directory of `.java` files has a `BUILD`
> file with a `java_library` target. A JVM target that has a
> `java_library` in its `dependencies` can import its code.
> `scala_library` targets are similar, but compiled with Scala.
>
> To use pre-built `.jar`s, a JVM target can depend on a `jar`, a
> reference to published code; these `jar`s normally live in a
> directory called
> [[3rdparty|pants('examples/src/java/com/pants/examples:3rdparty_jvm')]].
>
> Pants can `publish` a JVM library so code in other repos can use it;
> if the `*_library` target has a `provides` parameter, that specifies
> the repo/address at which to [[publish|pants('src/docs:publish')]].
>
> An `annotation_processor` BUILD target defines a Java library one
> containing one or more annotation processors.

**Tests**

> A `junit_tests` BUILD target holds source code for some JUnit tests;
> typically, it would have one or more `java_library` targets as
> dependencies and would import and test their code.
>
> A `scala_specs` target is similar, but has source code for Scala
> specs.
>
> The Pants `test` goal runs tests.

**Generated Code**

> A `java_thrift_library` generates Java code from `.thrift` source; a
> JVM target that has this target in its `dependencies` can `import` the
> generated Java code. A `java_protobuf_library` is similar, but
> generates Java code from protobuffer source. A `jaxb_library`
> definition generates code to read and write XML using an XML schema
> (.xsd files).

BUILD for a Simple Binary
-------------------------

The [Pants Build Java hello world
sample](https://github.com/pantsbuild/pants/tree/master/examples/src/java/com/pants/examples/hello)
code shows the BUILD file for a simple Java binary (in the `main/`
directory):

!inc[start-after=runnable&end-before=README page](hello/main/BUILD)

This small program has just one dependency. It is a library, a `java_library`, a compiled set of
source code from this workspace.

### Depending on a Library

The rule of thumb is that each directory of `.java` or `.scala` files
has a library target. If you find yourself thinking "we should move some
of this code to another directory," you probably also want to set up a
`BUILD` file with a `java_library` (or `scala_library`) target. Here we
see the library target which `main-bin` depends on. This library target
lives in `hello/greet/BUILD`:

!inc[start-after=LICENSE](hello/greet/BUILD)

This library could depend on other build targets and artifacts; if your
code imports something, that implies a `BUILD` dependency.

### A Test Target

The [Pants Java Hello World example
tests](https://github.com/pantsbuild/pants/tree/master/examples/tests/java/com/pants/examples/hello)
are normal JUnit tests. To run them with Pants, we need a target for
them:

!inc[start-after=Test the](../../../../../tests/java/com/pants/examples/hello/greet/BUILD)

As with other targets, this one depends on code that it imports. Thus, a typical test target
depends the library that it tests and perhaps some others (here, `junit`).
The dependency on `junit` is a "third party" dependency, a pre-compiled artifact whose source
lives somewhere outside the workspace.

### Depending on a Jar

The test example depends on a jar, `junit`. Instead of compiling from
source, Pants invokes ivy to fetch such jars. To reduce the danger of
version conflicts, we use the 3rdparty idiom: we keep references to
these "third-party" jars together in `BUILD` files under the `3rdparty/`
directory. Thus, the test has a `3rdparty` dependency:

!inc[start-after=Test the](../../../../../tests/java/com/pants/examples/hello/greet/BUILD)

The `BUILD` files in `3rdparty/` have targets like:

    :::python
    jar_library(name='junit',
                jars = [
                  jar(org='junit', name='junit-dep', rev='4.11').with_sources(),
                ],
                dependencies = [
                  ':hamcrest-core',
                ],
               )

Those <a pantsref="bdict_jar">`jar()` things</a> are references to public jars.
You can read more about
[[JVM 3rdparty dependencies|pants('examples/src/java/com/pants/examples:3rdparty_jvm')]].

The Usual Commands: JVM
-----------------------

**Make sure code compiles and tests pass:**

Use the `test` goal with the targets you're interested in. If they are test targets,
Pants runs the tests. If they aren't test targets, Pants still compiles them since it knows it
must compile before it can test.

    :::bash
    $ ./pants test examples/src/java/com/pants/examples/hello/:: examples/tests/java/com/pants/examples/hello/::

Assuming you use `junit_test` targets, output from the `junit` run is written to
`.pants.d/test/junit/`; you can see it on the console with `--no--suppress-output`:

    :::bash
    $ ./pants test.junit --no-suppress-output examples/tests/java/com/pants/examples/hello::


**Run just that one troublesome test class:** (assuming a JUnit test;
other frameworks use other flags)

    :::bash
    $ ./pants test.junit --test=com.pants.examples.hello.greet.GreetingTest examples/tests/java/com/pants/examples/hello/::

**Packaging Binaries**

To create a <a pantsref="jvm_bundles">bundle</a> (a binary and its dependencies, perhaps
including helper files):

    :::bash
    $ ./pants bundle --archive=zip examples/src/java/com/pants/examples/hello/main
       ...lots of build output...
    08:50:54 00:02       [create-monolithic-jar]
    08:50:54 00:02         [add-internal-classes]
    08:50:54 00:02         [jar-tool]
                       created dist/hello-example.zip
    08:50:54 00:02     [dup]
    08:50:54 00:02     [apk]
    08:50:54 00:02       [apk-bundle]
                   SUCCESS
    $

This generates a zipfile with runnable contents; instead of a zipfile, we could have put the
contents a directory tree, a giant jar, or something else.
<a pantsref="jvm_bundles">Learn more about bundles</a>.

Toolchain
---------

Pants uses [Ivy](http://ant.apache.org/ivy/) to resolve `jar` dependencies. To change how Pants
resolves these, configure `resolve.ivy`.

Pants uses [Nailgun](https://github.com/martylamb/nailgun) to speed up compiles. Nailgun is a
JVM daemon that runs in the background. This means you don't need to start up a JVM and load
classes for each JVM-based operation. Things go faster.

Pants uses Jmake, a dependency tracking compiler facade.

Java7 vs Java6, Which Java
--------------------------

Normally, Pants uses the first java it finds in `JDK_HOME`, `JAVA_HOME`, or `PATH`. To specify a
specific java version for just one pants invocation:

    :::bash
    $ JDK_HOME=/usr/lib/jvm/java-1.7.0-openjdk-amd64 ./pants ...

If you sometimes need to compile some code in Java 6 and sometimes Java 7, you can use a
`compile.java` command-line arg to specify Java version:

    :::bash
    ./pants bundle compile.java --target=7 --source=7 examples/src/java/com/pants/examples/hello/main

*BUT* beware: if you switch between Java versions, Pants doesn't realize
when it needs to rebuild. If you build with version 7, change some code,
then build with version 6, java 6 will try to understand java
7-generated classfiles and fail. Thus, if you've been building with one
Java version and are switching to another, you probably need to:

    :::bash
    $ ./pants clean-all

so that the next build starts from scratch.

**Note:** Currently, pants is known to work with OpenJDK version 7 or greater,
and Oracle JDK version 6 or greater.


<a pantsmark="jvm_bundles"></a>

Bundles: Deploy-able Runnable File Trees
----------------------------------------

You can enjoy your web service on your development machine's
`localhost`, but to let other people enjoy it, you probably want to copy
it to a server machine. With Pants, the easiest way to do this is to
create a *bundle*: a directory tree of `.jar` and helper files.

Our "hello world" sample application needs a configuration file to run
correctly. (You can try to run without the configuration file, but the
program crashes immediately.) We define a `jvm_app` that represents a
runnable binary and "bundles" of extra files:

!inc[start-after=Like Hello World&end-before=The binary](hello/main/BUILD)

Here, we keep the extra files in a subdirectory, `config/` so that they
don't clutter up this directory. (In this simple example, there's just
one file, so there isn't actually much clutter.) By using the
<a pantsref="bdict_bundle">`bundle`</a>'s
`relative_to` parameter, we "strip off" that
subdirectory; in the generated bundle, these extra files will be in the
top directory.

(If you want to set up a tree of static files but don't need it to be
runnable, you can define a `jvm_app` target with bundles (and/or
resources) but whose `jvm_binary` has no source or main; the resulting
bundle will have the files you want (along with a couple of
not-so-useful stub `.jar` files).)

### Generating a Bundle

Invoke `./pants bundle` on a JVM app or JVM binary target:

    :::bash
    $ ./pants bundle examples/src/java/com/pants/examples/hello/main:main

With options, you can tell Pants to archive the bundle in a zip, a tar, and some other common
formats. See the <a pantsref="oref_goal_bundle">bundle help</a> for built-in choices.

### Contents of a Bundle

The generated bundle is basically a directory tree containing `.jar`s
and extra files. The `.jar` in the top-level directory has a manifest so
you can run it with `java -jar`:

    :::bash
    $ cd dist/hello-example-bundle/
    $ java -jar hello-example.jar
    16:52:11 INFO : Hello, world!

The "bundle" is basically a tree of files:

    :::bash
    $ cd dist/hello-example-bundle/
    $ find .
    .
    ./greetee.txt
    ./hello-example.jar
    ./libs
    $ jar -tf hello-example.jar
    META-INF/
    META-INF/MANIFEST.MF
    com/
    com/pants/
    com/pants/examples/
    com/pants/examples/hello/
    com/pants/examples/hello/main/
    com/pants/examples/hello/main/HelloMain.class
    com/pants/example/
    com/pants/example/hello/
    com/pants/example/hello/world.txt
    com/pants/examples/hello/greet/
    com/pants/examples/hello/greet/Greeting.class


That `greetee.txt` file came from the `bundles=` parameter.
The `libs/` directory contains 3rdparty jars (if any). The `jar` in the top directory
contains code compiled for this target.

### Deploying a Bundle

Instead of just creating a directory tree, you can specify `bundle --archive=zip` to
`./pants bundle` to generate an archive file (a `.zip`, monolithic `.jar`, or some other
format) instead.

To use such an archive, put it where you want it, unpack it, and run:

    :::bash
    $ ./pants bundle --archive=zip examples/src/java/com/pants/examples/hello/main
        ...lots of build output...
    10:14:26 00:01       [create-monolithic-jar]
    10:14:26 00:01         [add-internal-classes]
    10:14:26 00:01         [jar-tool]
                       created dist/hello-example.zip
    10:14:26 00:01     [dup]
    10:14:26 00:01     [apk]
    10:14:26 00:01       [apk-bundle]
                   SUCCESS
    $ # let's use it:
    $ mkdir tmp; cd tmp
    $ unzip ../dist/hello-example.zip
    Archive:  ../dist/hello-example.zip
      inflating: greetee.txt
      inflating: hello-example.jar
    $ java -jar hello-example.jar
    Hello, Bundled-File World!
    Hello, Resource World!
    $

Omit Parts from Binary
----------------------

Sometimes you want to leave some files out of your binary.

You can omit jars from the binary by means of the `jvm_binary`'s `deploy_excludes` parameter.
For example, if you're making a binary to run on Hadoop and there are some "standard jars"
already on the destination machines, you can list those in `deploy_excludes`.

More generally, you can omit files from the binary jar with `deploy_jar_rules`. For example, a
3rdparty dependency might have a transitive dependency with a bad manifest file. If you try to run
the jar you might get `Invalid signature file digest for Manifest main attributes`. If you don't
actually use the code in that transitive dependency, you might work around the error by omitting
the dependency.

To tell Pants to omit some files from the binary, set the `deploy_jar_rules` parameter of
<a pantsref='bdict_jvm_binary'>`jvm_binary`</a> to a <a pantsref='bdict_jar_rules'>`jar_rules`</a>.
E.g., to omit all files containing the regexp `Greeting`, you might set

    :::python
    deploy_jar_rules=jar_rules(rules=[Skip('Greeting')])

After building our `hello` example, if we check the binary jar's contents, there is no
`Greeting.class` (and running that jar crashes; we omitted a class this binary needs):

    :::bash
    $ ./pants binary examples/src/java/com/pants/examples/hello/main:main
    $ jar -tf dist/hello-example.jar
    META-INF/
    META-INF/MANIFEST.MF
    com/
    com/pants/
    com/pants/examples/
    com/pants/examples/hello/
    com/pants/examples/hello/main/
    com/pants/examples/hello/main/HelloMain.class
    com/pants/example/
    com/pants/example/hello/
    com/pants/example/hello/world.txt
    $

Further Reading
---------------

If you use Scala, see
[[Scala Projects with Pants|pants('examples/src/scala/com/pants/examples:readme')]].

If you know Maven and want to know Pants equivalents, see
[[Pants for Maven Experts|pants('examples/src/java/com/pants/examples:from_maven')]].
