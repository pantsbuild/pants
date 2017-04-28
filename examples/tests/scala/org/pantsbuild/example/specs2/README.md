# Scala Specs2 Example

Pants supports Scala Specs2. In order for it to work you have to extend the `SpecificationWithJUnit` class, because Pants uses JUnit's runner to run tests.

You can run these tests with the command:

`./pants test examples/tests/scala/org/pantsbuild/example/specs2`

This target can also be imported in IntelliJ. If you choose to run it with IntelliJ Scala Runner, you can see a Specs2 run configuration generated under Run -> Edit Configurations.