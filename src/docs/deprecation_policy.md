Pants Deprecation Policy
========================

For releases after 1.0.0, deprecations are in effect for release branches until the next 2 minor releases (e.g. if the feature is available in 1.0.x it should continue to be available in 1.1.x and 1.2.x and can be removed in 1.3.x).

This assumes a rough timeline of 3 months lifetime per minor release.

API Definition
--------------

A module, variable, method, function or class is part of the public API if:

- Its definition's docstring is marked `:API: public`, and its enclosing definition, if any, is part of the public API.
- It's abstract or effectively abstract (required to be re-defined by the declaring class) and its declaring class or any inheriting class published by Pants is marked `:API: public`.

For example, a method `baz` of class `Bar` defined at the top level of module `foo` is part of the public API if and only if the docstrings of `foo`, `Bar` and `baz` are all marked `:API: public`. e.g.

    $ cat foo.py

    """
    An example public API module.

    :API: public
    """


    class Bar(object):
      """An example public API class.

      :API: public
      """

      def baz(self):
        """An example public API method.

        :API: public
        """


    def qux(self):
      """An example public API function.

      :API: public
      """

As a special exception, some legacy subsystem types are marked `:API: public` and implicitly have all their registered options exposed as `:API: public` members.
Going forward its expected new subsystem types are just factories for options-configured plain old types; so the type and its factory method will be the only `:API: public` members of subsytems.

The following rules apply to definitions in the public API. No rules apply to definitions outside the public API. Those may be changed in any way at any time.

In the case of a legal requirement to change API's we will make our best effort to minimize impact for plugin developers.

Allowed API Changes
-------------------

- Adding a new module.
- Adding new command line options.
- Adding new features to existing modules.
- Deprecate and warn about an API that has been refactored.
- Deprecate and warn about an option that has been refactored.
- Adding new named/defaulted parameters to a public API method.
- Adding/removing/renaming any module or method in a directory named 'exp'.
- Adding/removing/renaming any module or method not marked `:API: public` in the docstring.
- Fixing bugs.
  - Exceptions for severe or special case bugs may be considered on a case-by-case basis.
- API changes that would normally be disallowed but are legally required.

Disallowed API Changes
----------------------

- Deprecated options must continue to work as before.
- Existing API modules cannot be moved.
- Options cannot be removed.
- Parameters cannot be removed from API methods (any public method in an API module).
- Changing the behavior of a method that breaks existing assumptions.
  - e.g. changing a method that used to do transitive resolution to intransitive resolution would be disallowed, but adding a new named parameter to change the behavior would be allowed.
- Changes that introduce significant performance regressions by default.
  - A significant regression would be a slowdown of >= 10%.
  - If a new feature is needed that would slow down performance more than 10%, it should be put behind an option.
