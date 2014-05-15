##############################
Using Pants with IntelliJ IDEA
##############################

This page documents how to use Pants with
`IntelliJ IDEA <http://www.jetbrains.com/idea/>`_\.
(To use IntelliJ to work on Pants *itself*, see :doc:`intellij`.)

*******************************
Pants Build Plugin for IntelliJ
*******************************

For an installation walkthrough and quick demo, see
https://www.youtube.com/watch?v=mIr9BAi-1s4

***********************
Generating IDEA Project
***********************

To generate an IDEA project for the code in
``src/java/com/archie/path/to:target`` and
``src/java/com/archie/another:target``, use
the :ref:`idea goal <gref_phase_idea>`::

    goal idea src/java/com/archie/path/to:target src/java/com/archie/another:target

