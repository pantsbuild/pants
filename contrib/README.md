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
   The only hard requirement though is the `register.py` entry point file in the main src dir -
   in this example: `contrib/example/src/python/pants/contrib/example/register.py`.

   Source roots for this layout should match your source root patterns.  The default patterns
   are typically sufficient.

   **NB: python code should be in the pants/contrib and pants_test/contrib namespaces and the
   `__init__.py` files for these shared root namespaces should contain a namespace declaration
   like so:**
   ```python
   __import__('pkg_resources').declare_namespace(__name__)
   ```

2. Make the local pants aware of your plugin
   This involves 2 edits to `pants.ini`.  You'll need to add one entry in each of the
   `pythonpath` and `backend_packages` lists:
   ```ini
   [GLOBAL]
   # Enable our own custom loose-source plugins as well as contribs.
   pythonpath: [
       "%(buildroot)s/pants-plugins/src/python",
       ...
       "%(buildroot)s/contrib/example/src/python",  # 1
       ...
     ]

   backend_packages: [
       "internal_backend.repositories",
       "internal_backend.sitegen",
       "internal_backend.utilities",
       ...
       "pants.contrib.example",  # 2
       ...
     ]
   ```

3. When you're ready for your plugin to be distributed, convert your main `python_library` plugin
   target to a `contrib_plugin` target and register the plugin with the release script.

   The `contrib_plugin` target assumes 1 source of `register.py`; so, the sources argument should be
   removed.  It still accepts dependencies and other python target arguments with some special
   additions to help define the plugin distribution.  You'll need to supply a `distribution_name`
   and a `description` of the plugin suitable for [pypi](https://pypi.python.org/pypi) as well as
   parameters indicating which plugin entry points your plugin implements:
   ```python
   contrib_plugin(
     name='plugin',
     distribution_name='pantsbuild.pants.contrib.example',
     description='An example pants contrib plugin.'
     build_file_aliases=True,
     register_goals=True,
   )
   ```
   In this example, the plugin implements the `build_file_aliases` and `register_goals` entry point
   methods, but a plugin may additionally implement the `global_subsystems` entry point method, in
   which case it's `contrib_plugin` target would have a `global_subsystems=True,` entry as well.

   To register with the release script, add an entry to `contrib/release_packages.sh`:
   ```bash
   PKG_EXAMPLE=(
     "pantsbuild.pants.contrib.example"
     "//contrib/example/src/python/pants/contrib/example:plugin"
     "pkg_example_install_test"
   )
   function pkg_example_install_test() {
     execute_packaged_pants_with_internal_backends \
       --plugins="['pantsbuild.pants.contrib.example==$(local_version)']" \
       goals | grep "example-goal" &> /dev/null
   }

   # Once an individual (new) package is declared above, insert it into the array below)
   CONTRIB_PACKAGES=(
     PKG_SCROOGE
     PKG_EXAMPLE
   )
   ```
   NB: The act of releasing your contrib distribution is part of of the normal `pantsbuild.pants`
   [release process](https://www.pantsbuild.org/howto_contribute.html).  You may need to request
   a release from the owners if you have a change that should be fast-tracked before the next
   `pantsbuild.pants` release.  You can always test that your contrib distribution works though by
   doing a release dry run:
   ```bash
   ./build-support/bin/release.sh -n
   ```
