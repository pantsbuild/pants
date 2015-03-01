Pants plugin contributions
==========================

Pants plugins that are expected to be widely useful, but not shipped with core pants belong here.

Having plugin code live in the main pants repo allows plugin authors to have their plugin tested
and refactored alongside pants code while allowing pants core contributors a better grasp of how
plugin APIs are used.

Most new plugins should get their own top-level `contrib/` subdirectory although it may make sense
to house the source code for related plugins under one top-level `contrib/` subdirectory.  The
`contrib/scrooge` directory is an example of this and houses two plugin tasks that both use the same
underlying [Scrooge](https://github.com/twitter/scrooge) tool.

Contrib plugins should generally follow 3 basic setup steps:

1. Create a contrib source tree for the new plugin and register source roots
   A typical pure python layout would be:
   ```
   contrib/example/
     src/python/pants/contrib/example/...
     tests/python/pants_test/contrib/example/...
   ```
   Source roots for this layout would be added to contrib/BUILD:
   ```
   source_root('example/src/python', page, python_library, resources)
   source_root('example/tests/python', page, python_library, python_tests, resources)
   ```
   **NB: python code should be in the pants/contrib and pants_test/contrib namespaces and the
   `__init__.py` files for these shared root namespaces should contain a namespace declaration
   like so:**
   ```python
   __import__('pkg_resources').declare_namespace(__name__)
   ```

2. Make the local pants aware of your plugin
   This involves 2 edits to `pants.ini`, adding a `pythonpath` entry and a `packages` entry:
   ```ini
   [DEFAULT]
   # Enable our own custom loose-source plugins as well as contribs.
   pythonpath: [
       "%(buildroot)s/pants-plugins/src/python",
       "%(buildroot)s/contrib/scrooge/src/python",
       "%(buildroot)s/contrib/example/src/python",
     ]
   ...
   [backends]
   packages: [
       "internal_backend.optional",
       "internal_backend.repositories",
       "internal_backend.sitegen",
       "internal_backend.utilities",
       "pants.contrib.scrooge",
       "pants.contrib.example",
     ]
   ```

3. When you're ready for your plugin to be distributed, add a `provides` `contrib_setup_py`
   descriptor to your main plugin BUILD target and register the plugin with the release script.
   The `provides` descriptor just requires a name and description for your plugin suitable for
   [pypi](https://pypi.python.org/pypi):
   ```python
   python_library(
      name='plugin',
      sources=['register.py'],
      provides=contrib_setup_py(
        name='pantsbuild.pants.contrib.example',
        description='An example pants contrib plugin.'
      )
   )
   ```
   To register with the release script, add an entry to `contrib/release_packages.sh`:
   ```bash
   PKG_EXAMPLE=(
     "pantsbuild.pants.example"
     "//contrib/example/src/python/pants/contrib/example:plugin"
     "pkg_example_install_test"
   )
   function pkg_example_install_test() {
     PIP_ARGS="$@"
     pip install ${PIP_ARGS} pantsbuild.pants.example==$(local_version) && \
     execute_packaged_pants_with_internal_backends goals | grep "example-goal" &> /dev/null
   }

   # Once an individual (new) package is declared above, insert it into the array below)
   CONTRIB_PACKAGES=(
     PKG_SCROOGE
     PKG_EXAMPLE
   )
   ```
   NB: The act of releasing your contrib distribution is part of of the normal `pantsbuild.pants`
   [release process](https://pantsbuild.github.io/howto_contribute.html).  You may need to request
   a release from the owners if you have a change that should be fast-tracked before the next
   `pantsbuild.pants` release.  You can always test that your contrib distribution works though by
   doing a release dry run:
   ```bash
   ./build-support/bin/release.sh -n
   ```
