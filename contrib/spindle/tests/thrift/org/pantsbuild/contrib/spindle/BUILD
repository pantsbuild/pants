# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# XXX(pl): This is not a good place to declare source roots.
# In general, they shouldn't be declared in BUILD files, since
# that means we rely on BUILD file parsing and parse order to
# modify global state.  Furthermore, this can't be declared in
# the contrib plugin's register.py, since various downstream
# plugin consumers might have different source root layouts.
# And finally, it can't be declared in contrib/BUILD with the
# other contrib projects, since the self distribution tests
# expect to be able to parse that BUILD file without having
# the contrib plugins loaded--meaning in our case that
# `spindle_thrift_library` is not defined.
# It is declared here just for the purpose of getting minimal
# testing to work, and ideally in the future we will have
# a declarative way of specifying these source roots outside
# of BUILD files.
source_root('.', page, spindle_thrift_library)

spindle_thrift_library(
  name = 'tvlisting',
  sources = globs('*.thrift'),
)
