#Backwards Compatibility
##Summary

Releases must remain backwards compatible for at least 2 minor releases, post 1.0.
This assumes a rough timeline of 2 week lifetime per minor release.

**For example:** if the feature is available 1.0.x is should continue to be available in
1.1.x and 1.2.x and can be removed in 1.3.x.

This policy applies to:
Modules under src/test/python/pants_test that are marked `API:Public` in python docstrings

## Allowed API changes:
* Adding a new module
* Adding new command line options
* Adding new features to existing modules
* Deprecate and warn about an API that has been refactored
* Deprecate and warn about an option that has been refactored
* Adding new named parameters to a public API method
* Adding/removing/renaming any module or method in a directory named ‘exp’
  or starting with the prefix ‘_’
* Adding/removing/renaming any module prefixed with  ‘_’
* Adding/removing/renaming any method prefixed with ‘_’ or ‘private_’
* Fixing bugs
    * Caveat, sometimes builds rely on buggy behavior
    * Be more precise as to what a bug actually means and consider applying
      fixes on a  case-by-case basis.

## Disallowed API changes:
* Deprecated options must continue to work as before
* Existing API modules cannot be moved.
* Options cannot be removed
* Parameters cannot be removed from API methods (any public method in an API module)
* Changing the behavior of a method that breaks existing assumptions
    * e.g. changing a method that used to do transitive resolution to intransitive
      resolution would be disallowed, but adding a new named parameter to change the
      behavior would be allowed.
* Changes that introduce significant performance regressions by default
    * A significant regression would be a slowdown of > 10%
    * If a new feature is needed that would slow down performance more than 10%,
      it should be put behind an option
