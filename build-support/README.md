/build-support/

Scripts used to build Pants-related things. Scripts, config, and other infrastructure necessary
for Pants to function.

Python packages distributed to PyPI with pants are defined in a particular format in
bash:

Each package definition is of the form:

```bash
PKG_<NAME>=(
  "package.name"
  "build.target"
  "pkg_<name>_install_test"
  "bdist_wheel flags" # NB: this entry is optional.
)
function pkg_<name>_install_test() {
  ...
}
```

The arguments to the `pkg_<name>_install_test` function will always begin with
a requirements `name=version` string for the package, followed by any additional
arguments that should be passed to pip (if pip is used to test the package).
