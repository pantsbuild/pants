# NB: We need to declare a namespace package because we have the dists `pantsbuild.pants` and
# `pantsbuild.pants.testutil`, which both have the module `pants`.
__import__("pkg_resources").declare_namespace(__name__)
