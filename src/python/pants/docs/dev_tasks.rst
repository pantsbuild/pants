######################
Task Developer's Guide
######################

This page documents how to develop pants tasks, enabling you to teach pants
how to do things it does not already know how to do today. This page makes
more sense if you know the concepts from :doc:`internals`.


****************
PageRank Example
****************

Let's dive in an look at a fully-functional task.
Generating reports its a common user request, as folks often want to learn
more about their builds. Target dependencies and dependees are a couple
examples. Let's explore how to generate a new report, such as running PageRank
over the targets graph. Perhaps you're just curious to see what the most
popular targets are, or maybe you want to use that information to focus
testing efforts.

Let's remind ourselves of the simplified
`PageRank algorithm <http://www.cs.princeton.edu/~chazelle/courses/BIB/pagerank.htm>`_ ::

   PR(A) = (1-d) + d (PR(T1)/C(T1) + ... + PR(Tn)/C(Tn))

Where ``T`` are our targets, and dependencies are analogous to inbound links.
To perform such a calculation we simply need to walk the targets graph to
identify all target dependees, then perform the above calculation some number
of iterations, and finally display the results.

Now let's look at PageRank. First, notice we subclass ``ConsoleTask`` which
provides conveniences when generating reports. Also, notice we don't define
an explicit constructor as there's no configuration to setup nor do we need
to register product requirements. We implement ``console_output`` as
required by ``ConsoleTask`` which parses the targets graph, calculates
pagerank, then returns the report lines.

.. literalinclude:: pagerank.py
   :lines: 1-19

When processing dependencies we populate the maps by walking a filtered
targets graph. It's quite common for tasks to only know how to handle
specific target types.

.. literalinclude:: pagerank.py
   :lines: 21-32

Now let's calculate pagerank.

.. literalinclude:: pagerank.py
   :lines: 34-41

And finally return the report lines.

.. literalinclude:: pagerank.py
   :lines: 43-46

Let's see the report in action! Here we'll look at the most popular
target dependencies. As expected, foundational jars and targets
are identified. Let's say we wanted to restrict this report to
internal or external-only targets. Well... that's your homework :)

::

   $ ./pants goal pagerank src/java/com/twitter/common/:: | head
   8.283371 - com.google.code.findbugs-jsr305-1.3.9
   7.433371 - javax.inject-javax.inject-1
   7.433371 - com.google.guava-guava-14.0.1
   3.107220 - commons-lang-commons-lang-2.5
   2.537617 - com.google.inject-guice-3.0
   2.519704 - JavaLibrary(src/java/com/twitter/common/base/BUILD:base)
   2.205346 - javax.servlet-servlet-api-2.5
   2.042915 - org.hamcrest-hamcrest-core-1.2
   1.898855 - org.slf4j-slf4j-jdk14-1.6.1
   1.898855 - org.slf4j-slf4j-api-1.6.1

As you can see, generating reports is quite simple. We have the opportunity
to configure the task, and implement a simple interface that processes the
targets graph and generates a report on what it finds out.


*************
Core Concepts
*************


Task Base Class
===============

Let's examine the Task class, which is the "abstract class"
we'll need to subclass. The following simplified example highlights
the most useful methods.

* :py:class:`pants.tasks.__init__.Task` - This is the base class
  used to implement all the stuff pants knows how to do. When instantiating
  a task it has the opportunity to perform setup actions, or fetch
  configuration info from the context or ``pants.ini``. If it needs
  products produced by some other task it must register interest in
  those products (e.g.: "I'm a java compiler, I need java sources.").

* :py:meth:`pants.tasks.__init__.Task.execute` - Do some work.
  This is where the task does its thing. In addition to anything stashed
  away during instantiation, it has access to the targets graph.

* :py:meth:`pants.tasks.__init__.Task.setup_parser` - Specify
  command-line flags. These are useful for functionality that may be
  modified per-invocation. Use ``pants.ini`` for configuration that
  should always be used in the repo.


Targets Graph Traversal
=======================

Many tasks involve traversing the targets graph looking for targets of
particular types, and taking actions on those targets. For this reason
its important to understand now to navigate the targets graph.

The targets graph is provided to your
:py:meth:`pants.tasks.__init__.Task.execute` method, and you have
exclusive access to read and/or mutate it in place during execution.
Its provided as the list of *active concrete targets*. *Active* meaning
these targets are reachable by one or more ``target_roots`` specified on
the command-line; *concrete* meaning all targets resolve to themselves,
with any intermediate bags of ``dependencies`` removed.

Let's explore how to collect all targets of a particular type. ::

   def execute(self, targets):
     interesting_targets = set()
     for target in targets:
       target.walk(lambda t: interesting_targets.add(t),
                   lambda t: isinstance(t, FooLibrary)

First we need to iterate over ``targets``, which are the active concrete targets.
Then we ``walk`` each concrete target, providing as the first parameter
a callable that each walked target will be passed to. We also provide a callable
as the optional second parameter which filters the targets.

Traversing the targets graph is key to task development, as most tasks perform
some operation on the targets "in play." We iterate over the active concrete
targets, ``walk``\ ing each one with our visiting callable. By walking the
targets graph you can identify exactly which targets are necessary to implement
your task.


Task Installation
=================

Tasks must be installed before they are available for use.
Fortunately this is a simple process. They are installed
in ``goal.py`` as follows: ::

   from pants.tasks.pagerank import PageRank
   goal(name='pagerank', action=PageRank).install().with_description('PageRank the given targets.')



Task Configuration
==================

Tasks may be configured in two ways, through a configuration file checked
into the repo, and via command-line flags.

The configuration file is always called ``pants.ini`` and is a standard
``ini`` file loaded with ``ConfigParser``. During instantiation, tasks have
access to a :py:class:`pants.base.config.Config`
to read these settings. ::

   # Let's read mykey from the mytask pants.ini section.
   self.context.config.get('mytask', 'mykey')

Command-line flag values are also available during task instantiation. ::

   # Access a command-line flag the task defined.
   self.context.options.myflag


JVM Tool Bootstrapping
======================

If you want to integrate an existing JVM-based tool with a pants task, you need
to be able to bootstrap it, i.e., fetch it and create a classpath with which to run it.

Your job as a task
developer is to set up the arguments passed to your tool (e.g.: source file names
to compile) and do something useful after the tool has run. For example, a code
generation tool would identify targets that own IDL sources, pass those sources
as arguments to the code generator, create targets of the correct type to own
generated sources, and mutate the targets graph rewriting dependencies on targets
owning IDL sources to point at targets that own the generated code.

Tools are specified by targets in a special BUILD.tools file in the root of
your workspace. To bootstrap it you register that target under some key
in the task's __init__ method. Then, a special bootstrapping task will use Ivy
to resolve those targets. Then, in your execute() method you can get the
classpath for the tool using its registration key.

`Scalastyle <http://www.scalastyle.org/>`_ is a tool that enforces style policies
for scala code. Let's examine a simplified task that uses this tool. This example has been
condensed from the Scalastyle task provided by pants; please see its sources for a real-world
example, including exemplary configuration and error handling (which your task will have too,
right :)  ::

   class Scalastyle(NailgunTask):
     def __init__(self, context):
       NailgunTask.__init__(self, context)
       self._scalastyle_config = self.context.config.get_required('scalastyle, 'config')
       self._scalastyle_bootstrap_key = 'scalastyle'
       self.register_jvm_tool(self._scalastyle_bootstrap_key, [':scalastyle'])

     def execute(self, targets):
       srcs = get_scala_sources(targets)
       cp = self._jvm_tool_bootstrapper.get_jvm_tool_classpath(self._scalastyle_bootstrap_key)
       result = self.runjava(main='org.scalastyle.Main',
                             classpath=cp,
                             args=['-c', self._scalastyle_config] + srcs)
       if result != 0:
         raise TaskError('java %s ... exited non-zero (%i)' % ('org.scalastyle.Main', result))

Notice how we subclass ``NailgunTask``. This takes advantage of
`Nailgun <http://www.martiansoftware.com/nailgun/>`_ to speed up any tool with
a fixed classpath.
Our constructor is straightforward, simply identifying the configuration file and
registering the tool.
Our ``execute`` magically finds all the scala sources to check (we're focusing on
bootstrapping here), and fetches the classpath to use. Pay attention to the ``runjava`` line -
that's where the tool classpath is used. We simply say what main to execute, with what
classpath, and what program args to use. As Scalastyle is a barrier in our build, we fail
the build if files do not conform to the configured policy.

Note that the above description was a slight simplification. The bootstrapping task doesn't
actually invoke Ivy. Instead it creates a callback that invokes Ivy in just the right
way. This callback is called lazily on demand, the first time you call get_jvm_tool_classpath()
with a given key. This lazy invocation improves performance - we only invoke Ivy when we know
we really do need to use the tool.
