##############################
Using Pants with IntelliJ IDEA
##############################

This page documents how to use Pants with
`IntelliJ IDEA <http://www.jetbrains.com/idea/>`_\.
(To use IntelliJ to work on Pants *itself*, see :doc:`intellij`.)

***********************
Generating IDEA Project
***********************

Use ``goal idea`` to generate an IDEA project.

*******************
Editing BUILD Files
*******************

To edit ``BUILD`` files in IntelliJ IDEA, set them up for Python; ``BUILD``
files are valid Python, so you'll get syntax highlighting, etc.

If you have the IntelliJ Ultimate Edition, install/enable the Python plugin.
Associate ``BUILD`` and ``BUILD.*`` with the "Python script" file type.
You can make this association in one of the following ways:

* IntelliJ IDEA -> Preferences -> File Types -> Python script ->
  Add (at the Registered Patterns pane)
* Add the following to the extensionMap in
  ``~/Library/Preferences/IntelliJIdea10/options/filetypes.xml``::

      <mapping pattern="BUILD" type="Python" />
      <mapping pattern="BUILD.*" type="Python" />

If you have the IntelliJ Community Edition, associate those extensions with
the "Text files" file type, in one of the following ways:

* IntelliJ IDEA -> Preferences -> File Types -> Text files -> Add
  (at the Registered Patterns pane)
* Add the following to the extensionMap in
  ``~/Library/Preferences/IntelliJIdea10CE/options/filetypes.xml``::

      <mapping pattern="BUILD" type="PLAIN_TEXT" />
      <mapping pattern="BUILD.*" type="PLAIN_TEXT" />

This won't give you much in the way of syntax highlighting, but it will at
least allow you to edit the files in IntelliJ.

*******************************
Pants Build Plugin for IntelliJ
*******************************

For an installation walkthrough and quick demo, see
http://www.youtube.com/watch?v=mIr9BAi-1s4
