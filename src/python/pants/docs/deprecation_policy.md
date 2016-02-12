Pants Deprecation Policy
========================

For releases after 1.0.0, deprecations are in effect for release branches until the next 2 minor releases (e.g. if the feature is available in 1.0.x it should continue to be available in 1.1.x and 1.2.x and can be removed in 1.3.x).

This assumes a rough timeline of 3 months lifetime per minor release.

API Definition
--------------

This policy applies to:

- Modules under src/main/python/pants that do not start with an '_'.
- Modules under src/test/python/pants_test that are marked `:API: public` in the docstring.

Excluding
---------

- Modules under src/python/pants in directories named 'exp' or prefixed with '_'.
- Modules under tests/python/pants_test not marked `:API: public` in the docstring.
- Any module prefixed with '_'.
- Any method prefixed with '_'.
- Any method prefixed with 'private_'.
- Modules under any other directory including contrib, examples, testprojects.

Allowed API Changes
-------------------

- Adding a new module.
- Adding new command line options.
- Adding new features to existing modules.
- Deprecate and warn about an API that has been refactored.
- Deprecate and warn about an option that has been refactored.
- Adding new named parameters to a public API method.
- Adding/removing/renaming any module or method in a directory named 'exp' or starting with the prefix '_'.
- Adding/removing/renaming any module prefixed with  '_'.
- Adding/removing/renaming any method prefixed with '_' or 'private_'.
- Fixing bugs.
  - Exceptions for severe or special case bugs may be considered on a case-by-case basis.

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
