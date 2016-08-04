// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import com.google.common.base.Joiner;
import com.google.common.base.Splitter;
import java.util.ArrayList;
import java.util.List;
import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.junit.runners.Parameterized;
import org.junit.runners.Parameterized.Parameters;
import org.pantsbuild.junit.annotations.TestSerial;
import org.pantsbuild.tools.junit.impl.Concurrency;
import org.pantsbuild.tools.junit.impl.ConsoleRunnerImpl;

@TestSerial
@RunWith(Parameterized.class)
public abstract class ConsoleRunnerTestBase {
  private static final String DEFAULT_CONCURRENCY_FLAG = "-default-concurrency";
  private static final String DEFAULT_PARALLEL_FLAG = "-default-parallel";
  private static final String USE_EXPERIMENTAL_RUNNER_FLAG = "-use-experimental-runner";
  private static final String PARALLEL_THREADS_FLAG = "-parallel-threads";

  private static final String DEFAULT_TEST_PACKGE = "org.pantsbuild.tools.junit.lib.";

  protected TestParameters parameters;

  protected enum TestParameters {
    LEGACY_SERIAL(false, null),
    LEGACY_PARALLEL_CLASSES(false, Concurrency.PARALLEL_CLASSES),
    LEGACY_PARALLEL_METHODS(false, Concurrency.PARALLEL_METHODS),
    EXPERIMENTAL_SERIAL(true, Concurrency.SERIAL),
    EXPERIMENTAL_PARALLEL_CLASSES(true, Concurrency.PARALLEL_CLASSES),
    EXPERIMENTAL_PARALLEL_METHODS(true, Concurrency.PARALLEL_METHODS),
    EXPERIMENTAL_PARALLEL_CLASSES_AND_METHODS(true, Concurrency.PARALLEL_CLASSES_AND_METHODS);

    public final boolean useExperimentalRunner;
    public final Concurrency defaultConcurrency;

    TestParameters(boolean useExperimentalRunner, Concurrency defaultConcurrency) {
      this.useExperimentalRunner = useExperimentalRunner;
      this.defaultConcurrency = defaultConcurrency;
    }
    public String toString() {
      StringBuilder sb = new StringBuilder();
      if (useExperimentalRunner) {
        sb.append(USE_EXPERIMENTAL_RUNNER_FLAG);
        sb.append(" ");
      }
      if (defaultConcurrency != null) {
        sb.append(DEFAULT_CONCURRENCY_FLAG);
        sb.append(" ");
        sb.append(defaultConcurrency.name());
      }
      return sb.toString();
    }
  }

  @Parameters(name = "{0}")
  public static TestParameters[] data() {
    return TestParameters.values();
  }

  /**
   * The Parameterized test runner will invoke this test with each value in the
   * {@link TestParameters} enum.
   *
   * @param parameters A combination of extra parameters to test with.
   */
  public ConsoleRunnerTestBase(TestParameters parameters) {
    this.parameters = parameters;
  }

  @Rule
  public TemporaryFolder temporary = new TemporaryFolder();

  @Before
  public void setUp() {
    ConsoleRunnerImpl.setCallSystemExitOnFinish(false);
    ConsoleRunnerImpl.addTestListener(null);
    TestRegistry.reset();
  }

  @After
  public void tearDown() {
    ConsoleRunnerImpl.setCallSystemExitOnFinish(true);
    ConsoleRunnerImpl.addTestListener(null);
  }

  /**
   * Invokes ConsoleRunner.main() and tacks on optional parameters specified by the parameterized
   * test runner.
   */
  protected void invokeConsoleRunner(String argsString) {
    List<String> testArgs = new ArrayList<String>();
    for (String arg : Splitter.on(" ").split(argsString)) {
      // Prepend the package name to tests to allow shorthand command line invocation
      if (arg.contains("Test") && !arg.contains(DEFAULT_TEST_PACKGE)) {
        arg = DEFAULT_TEST_PACKGE + arg;
      }
      testArgs.add(arg);
    }

    // Tack on extra parameters from the Parameterized runner
    if (!testArgs.contains(DEFAULT_CONCURRENCY_FLAG) && parameters.defaultConcurrency != null) {
      if (!testArgs.contains(DEFAULT_CONCURRENCY_FLAG)
          && !testArgs.contains(DEFAULT_PARALLEL_FLAG)) {
        testArgs.add(DEFAULT_CONCURRENCY_FLAG);
        testArgs.add(parameters.defaultConcurrency.name());
      }
      if (!testArgs.contains(PARALLEL_THREADS_FLAG)) {
        testArgs.add(PARALLEL_THREADS_FLAG);
        testArgs.add("8");
      }
    }
    if (!testArgs.contains(USE_EXPERIMENTAL_RUNNER_FLAG) && parameters.useExperimentalRunner) {
      testArgs.add(USE_EXPERIMENTAL_RUNNER_FLAG);
    }
    System.out.println("Invoking ConsoleRunnerImpl.main(\""
        + Joiner.on(' ').join(testArgs) + "\")");

    ConsoleRunnerImpl.main(testArgs.toArray(new String[testArgs.size()]));
  }
}
