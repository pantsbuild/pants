
TODOs
--------

#### Refactoring
TODO move sec console runner tests into their own files

#### Attribution / Messaging
TODO Record where the thread was started and including that in the message
TODO collapse common initialization errors in test runs.
TODO ensure that this has a clear error
  The question here is whether it should fail before running the tests. Right now it runs them,
  but the resulting error is
  java.lang.ExceptionInInitializerError
  at sun.reflect.NativeConstructorAccessorImpl.newInstance0(Native Method)
  ... 50 lines ...
  Caused by: java.lang.SecurityException: System.exit calls are not allowed.
  at org.pantsbuild.tools.junit.impl.security.JunitSecViolationReportingManager
  I think it should either end with 0 tests run 1 error, or
  2 run, 2 error, with a better error than ExceptionInInitializerError

#### Network
TODO handle more ways to say localhost
TODO look up host name and fail if it's not localhost



#### Hardening / Resilience
TODO reset context tree after test run --- maybe need to have a notion of a session?

TODO scope checks
- In test vs not

TODO how to interact with existing security managers -- maybe complain with a note about how to
fix it?
TODO assert that a fail fast does not trigger a security manager fail

#### File access
TODO file access
  - allowAll
  - disallowAll
  - onlyInCWD
  - add support on the pants side

Per Target
TODO per-target config.
  Qs
    - how to pass it to the tool? Config file?
    - how does overriding work?
      - can only narrow?
      - can only widen?
      - force some, allow changes for others? Locked?


