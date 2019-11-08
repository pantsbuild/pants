/build-support/

Scripts used to build Pants-related things. Scripts, config, and other infrastructure necessary
for Pants to function.

Python packages distributed to PyPI with pants are defined in two parts:
Metadata in src/python/pants/releases/packages.py and a function accessible from release.sh
with name `pkg_<name>_install_test` where `<name>` is the text after the last `.` in the package name.

The arguments to the `pkg_<name>_install_test` function are the version string to test,
followed by zero or more pip args (for use if pip is going to be used to test the package).
All contrib tests are run as part of CI, so the `pkg_<name>_install_test` function should
generally only sanity check that a module is properly importable as a plugin.
