python_sources()

resource(name="importlinter", source=".importlinter")

python_requirement(
    name="pants.testutil",
    modules=["pants.testutil"],
    requirements=["pantsbuild.pants.testutil"],
)

python_tests(
    name="rules_integration_test",
    sources=["rules_integration_test.py"],
    dependencies=[":importlinter"],
    timeout=240,
)
