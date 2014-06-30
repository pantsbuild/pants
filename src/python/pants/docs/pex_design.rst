==========
PEX Design
==========

But why another system?

Alternatives
^^^^^^^^^^^^

There are several solutions for package management in Python.  Almost
everyone is familiar with running `sudo easy_install PackageXYZ`.  This
leaves a lot to be desired.  Over time, your Python installation will
collect dozens of packages, become annoyingly slow or even broken, and
reinstalling it will invariably break a number of the applications
that you were using.

A marked improvement over the `sudo easy_install` model is virtualenv_
to isolate Python environments on a project by project basis.  This is
useful for development but does not directly solve any problems
related to deployment, whether it be to a production environment or to
your peers.  It is also challenging to explain to a Python non-expert.

.. _virtualenv: http://www.virtualenv.org

A different solution altogether, `zc.buildout`_ attempts to provide a
framework and recipes for many common development environments.  It
has arguably gone the farthest for automating environment
reproducibility amongst the popular tools, but shares the same
complexity problems as all the other abovementioned solutions.

.. _zc.buildout: http://www.buildout.org/

Most solutions leave deployment as an afterthought.  Why not make the
development and deployment environments the same by taking the
environment along with you?

Pants and PEX
^^^^^^^^^^^^^

The lingua franca of Pants is the PEX file (PEX itself does not stand for
anything in particular, though in spirit you can think of it as a "Python
EXecutable".)

**PEX files are single-file lightweight virtual Python environments.**

The only difference is no virtualenv setup instructions or
`pip install foo bar baz`.  PEX files are self-bootstrapping Python
environments with no strings attached and no side-effects.  Just a simple
mechanism that unifies both your development and your deployment.

How PEX files work
------------------

the utility of zipimport and `__main__.py`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

As an aside, in Python, you may not know that you can import code from directories:

.. code-block:: bash
                
  $ mkdir -p foo
  $ touch foo/__init__.py
  $ echo "print 'spam'" > foo/bar.py
  $ python -c 'import foo.bar'
  spam


All that is necessary is the presence of `__init__.py` to signal to the importer that we
are dealing with a package.  Similarly, a directory can be made "executable":

.. code-block:: bash

  $ echo "print 'i like flowers'" > foo/__main__.py
  $ python foo
  i like flowers


And because the `zipimport` module now provides a default import hook for
Pythons >= 2.4, if the Python import framework sees a zip file, with the
inclusion of a proper `__init__.py`, it can be treated similarly to a
directory.  But since a directory can be executable, if we just drop a
`__main__.py` into a zip file, it suddenly becomes executable:

.. code-block:: bash

  $ pushd foo && zip /tmp/flower.zip __main__.py && popd
  /tmp/foo /tmp
    adding: __main__.py (stored 0%)
  /tmp
  $ python flower.zip
  i like flowers

And since zip files don't actually start until the zip magic number, you can
embed arbitrary strings at the beginning of them and they're still valid
zips.  Hence simple PEX files are born:

.. code-block:: bash

  $ echo '#!/usr/bin/env python2.6' > flower.pex && cat flower.zip >> flower.pex
  $ chmod +x flower.pex
  $ ./flower.pex
  i like flowers


Remember `pants.pex`?

.. code-block:: bash
                
  $ unzip -l pants.pex | tail -2
  warning [pants.pex]:  25 extra bytes at beginning or within zipfile
    (attempting to process anyway)
   --------                   -------
    7900812                   543 files

  $ head -c 25 pants.pex
  #!/usr/bin/env python2.6

PEX `__main__.py`
^^^^^^^^^^^^^^^^^

The `__main__.py` in a real PEX file is somewhat special::

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

`PEX` is just a class that manages requirements (often embedded within PEX
files as egg distributions in the `.deps` directory) and autoimports them
into the `sys.path`, then executes a prescribed entry point.

If you read the code closely, you'll notice that it relies upon monkeypatching `zipimport`.  Inside
the `twitter.common.python` library we've provided a recursive zip importer derived from Google's
`pure Python zipimport <http://code.google.com/appengine/articles/django10_zipimport.html>`_ module
that allows for depending upon eggs within eggs or zips (and so forth) so that PEX files need not
extract egg dependencies to disk a priori.  This even extends to C extensions (.so and .dylib
files) which are written to disk long enough to be dlopened before being unlinked.

Strictly speaking this monkeypatching is not necessary and we may consider
making that optional.
