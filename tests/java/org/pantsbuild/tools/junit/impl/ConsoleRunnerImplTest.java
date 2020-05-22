// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.PrintStream;
import java.io.UnsupportedEncodingException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.List;
import java.util.function.Predicate;
import java.util.stream.Collectors;
import java.util.stream.StreamSupport;

import com.google.common.base.Charsets;
import com.google.common.collect.Lists;

import org.hamcrest.Description;
import org.hamcrest.Matcher;
import org.hamcrest.TypeSafeDiagnosingMatcher;
import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.Result;
import org.junit.runner.notification.RunListener;
import org.junit.runner.notification.StoppedByUserException;
import org.pantsbuild.tools.junit.lib.AllFailingTest;
import org.pantsbuild.tools.junit.lib.AllIgnoredTest;
import org.pantsbuild.tools.junit.lib.AllPassingTest;
import org.pantsbuild.tools.junit.lib.ExceptionInSetupTest;
import org.pantsbuild.tools.junit.lib.LogOutputInTeardownTest;
import org.pantsbuild.tools.junit.lib.OutputModeTest;
import org.pantsbuild.tools.junit.lib.XmlReportTest;
import org.pantsbuild.tools.junit.lib.XmlReportTestSuite;

import static org.hamcrest.CoreMatchers.containsString;
import static org.hamcrest.CoreMatchers.not;
import static org.hamcrest.MatcherAssert.assertThat;
import static org.hamcrest.core.Is.is;
import static org.junit.Assert.fail;

/**
 * These tests are similar to the tests in ConsoleRunnerTest but they create a ConsoleRunnerImpl
 * directory so they can capture and make assertions on the output.
 */
public class ConsoleRunnerImplTest {

  @Rule
  public TemporaryFolder temporary = new TemporaryFolder();

  private boolean failFast;
  private ConsoleRunnerImpl.OutputMode outputMode;
  private boolean xmlReport;
  private File outdir;
  private boolean perTestTimer;
  private Concurrency defaultConcurrency;
  private int parallelThreads;
  private int testShard;
  private int numTestShards;
  private int numRetries;
  private boolean useExperimentalRunner;

  @Before
  public void setUp() {
    resetParameters();
    ConsoleRunnerImpl.setCallSystemExitOnFinish(false);
    ConsoleRunnerImpl.addTestListener(null);
  }

  @After
  public void tearDown() {
    ConsoleRunnerImpl.setCallSystemExitOnFinish(true);
    ConsoleRunnerImpl.addTestListener(null);
  }

  private void resetParameters() {
    failFast = false;
    outputMode = ConsoleRunnerImpl.OutputMode.ALL;
    xmlReport = false;
    try {
      outdir = temporary.newFolder();
    } catch (IOException e) {
      throw new RuntimeException(e);
    }
    perTestTimer = false;
    defaultConcurrency = Concurrency.SERIAL;
    parallelThreads = 0;
    testShard = 0;
    numTestShards = 0;
    numRetries = 0;
    useExperimentalRunner = false;
  }

  private String runTestExpectingSuccess(Class testClass) {
    return runTests(
        Lists.newArrayList(testClass.getCanonicalName()),
        false);
  }

  private String runTestExpectingFailure(Class<?> testClass) {
    return runTests(
        Lists.newArrayList(testClass.getCanonicalName()),
        true
    );
  }

  private String runTests(
      List<String> tests,
      boolean shouldFail
  ) {
    PrintStream originalOut = System.out;
    PrintStream originalErr = System.err;

    ByteArrayOutputStream outContent = new ByteArrayOutputStream();
    PrintStream outputStream = new PrintStream(outContent, true);
    try {
      return createAndRunConsoleRunner(
          tests,
          shouldFail,
          originalOut,
          outContent,
          outputStream
      );
    } finally {
      System.setOut(originalOut);
      System.setErr(originalErr);
    }
  }

  private String createAndRunConsoleRunner(
      List<String> tests,
      boolean shouldFail,
      PrintStream originalOut,
      ByteArrayOutputStream outContent,
      PrintStream outputStream
  ) {

    // Clean log files
    for (File file : outdir.listFiles()) {
      if (file.getName().endsWith("txt")) {
        file.delete();
      }
    }

    ConsoleRunnerImpl runner = new ConsoleRunnerImpl(
        failFast,
        outputMode,
        xmlReport,
        perTestTimer,
        outdir,
        defaultConcurrency,
        parallelThreads,
        testShard,
        numTestShards,
        numRetries,
        useExperimentalRunner,
        outputStream,
        System.err  // TODO, if there's an error reported on system err, it doesn't show up in
        // the test failures.
    );

    try {
      runner.run(tests);
      if (shouldFail) {
        fail("Expected RuntimeException.\n====stdout====\n" + outContent.toString());
      }
    } catch (StoppedByUserException e) {
      // NB StoppedByUserException is used by the junit runner to cancel a test run for fail fast.
      if (!shouldFail) {
        throw e;
      }
    } catch (RuntimeException e) {
      boolean wasNormalFailure = e.getMessage() != null &&
          e.getMessage().contains("ConsoleRunner exited with status");
      if (!shouldFail || !wasNormalFailure) {
        System.err.println("\n====stdout====\n" + outContent.toString());
        throw e;
      }
    }

    try {
      return outContent.toString(Charsets.UTF_8.toString());
    } catch (UnsupportedEncodingException e) {
      throw new RuntimeException(e);
    }
  }

  @Test
  public void testFailFast() {
    failFast = false;
    String output = runTestExpectingFailure(AllFailingTest.class);
    assertThat(output, containsString("There were 4 failures:"));
    assertThat(output, containsString("Tests run: 4,  Failures: 4"));

    failFast = true;
    output = runTestExpectingFailure(AllFailingTest.class);
    assertThat(Arrays.asList(output.split("\n")),
        hasExactlyOneOf(containsString("There was 1 failure:")));
    assertThat(output, containsString("Tests run: 1,  Failures: 1"));
  }

  @Test
  public void testFailFastWithMultipleThreads() {
    failFast = false;
    parallelThreads = 8;
    String output = runTestExpectingFailure(AllFailingTest.class);
    assertThat(output, containsString("There were 4 failures:"));
    assertThat(output, containsString("Tests run: 4,  Failures: 4"));

    failFast = true;
    parallelThreads = 8;
    output = runTestExpectingFailure(AllFailingTest.class);
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("Tests run: 1,  Failures: 1"));
  }

  @Test
  public void testPerTestTimer() {
    perTestTimer = false;
    String output = runTestExpectingSuccess(AllPassingTest.class);
    assertThat(output, containsString("...."));
    assertThat(output, containsString("OK (4 tests)"));
    assertThat(output, not(containsString("AllPassingTest")));

    perTestTimer = true;
    output = runTestExpectingSuccess(AllPassingTest.class);

    assertThat(output, containsString(
        "org.pantsbuild.tools.junit.lib.AllPassingTest#testPassesOne"));
    assertThat(output, containsString(
        "org.pantsbuild.tools.junit.lib.AllPassingTest#testPassesTwo"));
    assertThat(output, containsString(
        "org.pantsbuild.tools.junit.lib.AllPassingTest#testPassesThree"));
    assertThat(output, containsString(
        "org.pantsbuild.tools.junit.lib.AllPassingTest#testPassesFour"));
    assertThat(output, containsString("OK (4 tests)"));
    assertThat(output, not(containsString("....")));
  }

  @Test
  public void testOutputMode() {
    outputMode = ConsoleRunnerImpl.OutputMode.ALL;
    String output = runTestExpectingFailure(OutputModeTest.class);
    assertThat(output, containsString("Output in classSetUp"));
    assertThat(output, containsString("Output in setUp"));
    assertThat(output, containsString("Output in tearDown"));
    assertThat(output, containsString("Output in classTearDown"));
    assertThat(output, containsString("There were 2 failures:"));
    assertThat(output, containsString("Output from passing test"));
    assertThat(output, containsString("Output from failing test"));
    assertThat(output, containsString("Output from error test"));
    assertThat(output, not(containsString("Output from ignored test")));
    assertThat(output, containsString("testFails(org.pantsbuild.tools.junit.lib.OutputModeTest)"));
    assertThat(output, containsString("testErrors(org.pantsbuild.tools.junit.lib.OutputModeTest)"));
    assertThat(output, containsString("Tests run: 3,  Failures: 2"));
    String testLogContents = getTestLogContents(OutputModeTest.class, ".out.txt");
    assertThat(testLogContents, containsString("Output from passing test"));

    outputMode = ConsoleRunnerImpl.OutputMode.FAILURE_ONLY;
    output = runTestExpectingFailure(OutputModeTest.class);

    assertThat(output, containsString("Output in classSetUp"));
    assertThat(output, containsString("Output in setUp"));
    assertThat(output, containsString("Output in tearDown"));
    assertThat(output, not(containsString("Output in classTearDown")));
    assertThat(output, containsString("There were 2 failures:"));
    assertThat(output, not(containsString("Output from passing test")));
    assertThat(output, containsString("Output from failing test"));
    assertThat(output, containsString("Output from error test"));
    assertThat(output, not(containsString("Output from ignored test")));
    assertThat(output, containsString("testFails(org.pantsbuild.tools.junit.lib.OutputModeTest)"));
    assertThat(output, containsString("testErrors(org.pantsbuild.tools.junit.lib.OutputModeTest)"));
    assertThat(output, containsString("Tests run: 3,  Failures: 2"));
    testLogContents = getTestLogContents(OutputModeTest.class, ".out.txt");
    assertThat(testLogContents, containsString("Output from passing test"));

    outputMode = ConsoleRunnerImpl.OutputMode.NONE;
    output = runTestExpectingFailure(OutputModeTest.class);
    assertThat(output, containsString("Output in classSetUp"));
    assertThat(output, not(containsString("Output in setUp")));
    assertThat(output, not(containsString("Output in tearDown")));
    assertThat(output, not(containsString("Output in classTearDown")));
    assertThat(output, containsString("There were 2 failures:"));
    assertThat(output, not(containsString("Output from passing test")));
    assertThat(output, not(containsString("Output from failing test")));
    assertThat(output, not(containsString("Output from error test")));
    assertThat(output, not(containsString("Output from ignored test")));
    assertThat(output, containsString("testFails(org.pantsbuild.tools.junit.lib.OutputModeTest)"));
    assertThat(output, containsString("testErrors(org.pantsbuild.tools.junit.lib.OutputModeTest)"));
    assertThat(output, containsString("Tests run: 3,  Failures: 2"));
    testLogContents = getTestLogContents(OutputModeTest.class, ".out.txt");
    assertThat(testLogContents, containsString("Output from passing test"));
  }

  @Test
  public void testOutputModeExceptionInBefore() {
    outputMode = ConsoleRunnerImpl.OutputMode.ALL;
    String output = runTestExpectingFailure(ExceptionInSetupTest.class);
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("java.lang.RuntimeException"));
    assertThat(output, containsString("Tests run: 0,  Failures: 1"));
    assertThat(output, not(containsString("Test mechanism")));

    outputMode = ConsoleRunnerImpl.OutputMode.FAILURE_ONLY;
    output = runTestExpectingFailure(ExceptionInSetupTest.class);
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("java.lang.RuntimeException"));
    assertThat(output, containsString("Tests run: 0,  Failures: 1"));
    assertThat(output, not(containsString("Test mechanism")));

    outputMode = ConsoleRunnerImpl.OutputMode.NONE;
    output = runTestExpectingFailure(ExceptionInSetupTest.class);
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("java.lang.RuntimeException"));
    assertThat(output, containsString("Tests run: 0,  Failures: 1"));
    assertThat(output, not(containsString("Test mechanism")));
  }

  @Test
  public void testOutputModeTestSuite() {
    outputMode = ConsoleRunnerImpl.OutputMode.ALL;
    String output = runTestExpectingFailure(XmlReportTestSuite.class);
    assertThat(output, containsString("There were 2 failures:"));
    assertThat(output, containsString("Test output"));
    assertThat(output, containsString("Tests run: 5,  Failures: 2"));
    assertThat(output, not(containsString("Test mechanism")));
    File testSuiteLogFile =
        new File(outdir.getPath(), XmlReportTestSuite.class.getCanonicalName() + ".out.txt");
    assertThat(testSuiteLogFile.exists(), is(false));
    String testLogContents = getTestLogContents(XmlReportTest.class, ".out.txt");
    assertThat(testLogContents, containsString("Test output"));
  }

  @Test
  public void testOutputModeIgnoredTest() {
    File testSuiteLogFile =
        new File(outdir.getPath(), AllIgnoredTest.class.getCanonicalName() + ".out.txt");

    outputMode = ConsoleRunnerImpl.OutputMode.ALL;
    String output = runTestExpectingSuccess(AllIgnoredTest.class);
    assertThat(testSuiteLogFile.exists(), is(false));
    assertThat(output, containsString("OK (0 tests)"));
    assertThat(output, not(containsString("testIgnore")));

    outputMode = ConsoleRunnerImpl.OutputMode.FAILURE_ONLY;
    output = runTestExpectingSuccess(AllIgnoredTest.class);
    assertThat(testSuiteLogFile.exists(), is(false));
    assertThat(output, containsString("OK (0 tests)"));
    assertThat(output, not(containsString("testIgnore")));

    outputMode = ConsoleRunnerImpl.OutputMode.NONE;
    output = runTestExpectingSuccess(AllIgnoredTest.class);
    assertThat(testSuiteLogFile.exists(), is(false));
    assertThat(output, containsString("OK (0 tests)"));
    assertThat(output, not(containsString("testIgnore")));
  }

  /**
   * This test reproduces a problem reported in https://github.com/pantsbuild/pants/issues/3638
   */
  @Test
  public void testRunFinishFailed() throws Exception {
    class AbortInTestRunFinishedListener extends RunListener {
      @Override public void testRunFinished(Result result) throws Exception {
        throw new IOException("Bogus IOException");
      }
    }
    ConsoleRunnerImpl.addTestListener(new AbortInTestRunFinishedListener());

    String output = runTestExpectingFailure(AllPassingTest.class);
    assertThat(output, containsString("OK (4 tests)"));
    assertThat(output, containsString("java.io.IOException: Bogus IOException"));
  }

  @Test
  public void testOutputAfterTestFinished() {
    outputMode = ConsoleRunnerImpl.OutputMode.ALL;
    String output = runTestExpectingSuccess(LogOutputInTeardownTest.class);
    assertThat(output, containsString("Output in tearDown"));
    assertThat(output, containsString("OK (3 tests)"));
    String testLogContents = getTestLogContents(LogOutputInTeardownTest.class, ".out.txt");
    assertThat(testLogContents, containsString("Output in tearDown"));

    outputMode = ConsoleRunnerImpl.OutputMode.FAILURE_ONLY;
    output = runTestExpectingSuccess(LogOutputInTeardownTest.class);
    assertThat(output, not(containsString("Output in tearDown")));
    assertThat(output, containsString("OK (3 tests)"));
    testLogContents = getTestLogContents(LogOutputInTeardownTest.class, ".out.txt");
    assertThat(testLogContents, containsString("Output in tearDown"));

    outputMode = ConsoleRunnerImpl.OutputMode.NONE;
    output = runTestExpectingSuccess(LogOutputInTeardownTest.class);
    assertThat(output, not(containsString("Output in tearDown")));
    assertThat(output, containsString("OK (3 tests)"));
    testLogContents = getTestLogContents(LogOutputInTeardownTest.class, ".out.txt");
    assertThat(testLogContents, containsString("Output in tearDown"));
  }

  private String getTestLogContents(Class testClass, String extension) {
    try {
      return new String(
          Files.readAllBytes(Paths.get(outdir.getPath(), testClass.getCanonicalName() + extension)),
          Charsets.UTF_8);
    } catch (IOException e) {
      throw new RuntimeException(e);
    }
  }

  private <T> Matcher<Iterable<T>> hasExactlyOneOf(final Matcher<T> elemMatcher) {
    return new ExactlyOneOf<T>(elemMatcher);
  }

  private static class ExactlyOneOf<T> extends TypeSafeDiagnosingMatcher<Iterable<T>> {
    private final Matcher<? super T> elemMatcher;

    public ExactlyOneOf(Matcher<? super T> elemMatcher) {
      this.elemMatcher = elemMatcher;
    }

    @Override
    protected boolean matchesSafely(Iterable<T> iterable,
                                    Description mismatchDescription) {
      List<T> filtered = StreamSupport.stream(iterable.spliterator(), false)
          .filter(new Predicate<T>() {
            @Override public boolean test(T input) {
              return elemMatcher.matches(input);
            }
          }).collect(Collectors.toList());
      if (filtered.isEmpty()) {
        mismatchDescription.appendText("found none in " + iterable);
        return false;
      } else if (filtered.size() > 1) {
        mismatchDescription.appendText("found more than one");
        return false;
      } else {
        return true;
      }
    }

    @Override
    public void describeTo(Description description) {
      description.appendText("exactly one of ");
      elemMatcher.describeTo(description);
    }
  }
}
