/tests/

Pants test targets. These tend to be `python_tests` exercising Pants functions.

`pants_test.base_build_root_test.BaseBuildRootTest` is a very handy class; it has methods to set
up and tear down little source trees with `BUILD` files.
