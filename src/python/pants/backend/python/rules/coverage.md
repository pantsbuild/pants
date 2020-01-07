## How Python Coverage Works
- running pytest generates data and drops a sql file, `.coverage` in the chroot.
- running `coverage combine` on a list of `.coverage` files merges them into a single `.coverage` sql file.
- running `coverage html` or `coverage xml` on a single `.coverage` file generates a report.


## Pants Architecture for Coverage
- Leave specific coverage options (e.g XML vs. Json output) to each language through a subsystem for that language’s coverage provider, e.g. pytest-cov
- Core test gets a `--coverage` option which just turns coverage on and off. It also writes down the coverage reports via `workspace.materialize_directory` It should probably also log something like
  `Python coverage report saved at coverage/python.xml`
  `Junit coverage report saved at coverage/junit.xml`
- Add a new concrete dataclass called something like `CoverageResult` or `MergedCoverageResult`, along with using a union so that languages provide their own implementation to create the standardized `CoverageResult` when test `--coverage` is true
- Languages create their own rules for running coverage. For python this will likely be:
  - `pytest-coverage-config` - new rule to generate a coveragerc file.
  - `python-test-runner` - update exising rule to turn on pytest-cov and inject the coveragerc file into the chroot.
  - `coverage-merge` - new rule merges the coverage data of individual test runs, also uses the coveragerc file. Outputs a merged data file.
  - `coverage-report` - new rule generates the xml/html report as a `CoverageResult`


## End result
`./pants test --coverage some/package:: some/other/package::` results in one coverage report per language dropped in some reasonable location.

## Other Considerations
- Do we want to be able to turn on/off coverage for particular languages? eg:
  `./pants test --coverage --pytest-cov-skip src:: test::`
- Should `--coverage-output-dir` be possible to be configured per language or should it always be the same? `--pytest-cov-output-dir` and `--cobertura-output-dir` vs `--test-coverage-output-dir`?
- In V1, the `--coverage` option takes arguments on which packages to generate coverage for. Do we want to maintain that behavior (probably under a new option `--pytest-cov-packages-to-cover` ) or just use the current behavior of `auto` in which we attempt to deduce which packages to cover via the `coverage` field in BUILD files or by assuming `test/python/foo` provides coverage to `src/python/foo`
