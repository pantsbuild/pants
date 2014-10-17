#########################
Developing a Pants Plugin
#########################

*As of September 2014, this process is new and still evolving;*
*expect it to change somewhat.*

This page documents how to develop a Pants plugin, a set of code
that defines new Pants functionality. If you
:doc:`develop a new task <dev_tasks>`
or target to add to Pants (or to override an existing part of Pants),
a plugin gives you a way to register your code with Pants.

Much of Pants' own functionality is organized in plugins; see
them in ``src/python/pants/backend/*``.

A plugin registers its functionality with Pants by defining some
functions in a ``register.py`` file in its top directory.
For example, Pants' ``jvm`` code registers in
`src/python/pants/backend/jvm/register.py
<https://github.com/pantsbuild/pants/blob/master/src/python/pants/backend/jvm/register.py>`_
Pants' backend-loader code assumes your plugin has a ``register.py``
file there.
