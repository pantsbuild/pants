##########################
Custom Pants for Your Site
##########################

*As of September 2014, this process is new and still evolving;*
*expect it to change plenty.*

You might want to tailor Pants' behavior for your organization
by defining some special functionality. If your changes are
generally-useful, you could :doc:`add them to Pants proper <howto_contribute>`.
But perhaps your organization has, e.g., some custom code generation
that wouldn't be of use to other organizations. You want to add some
functionality to Pants in a maintainable way.

At a high level, you want to
:doc:`develop a Pants plugin <howto_plugin>`
and create an altered Pants that registers your Plugin in addition
to the regular ones.


