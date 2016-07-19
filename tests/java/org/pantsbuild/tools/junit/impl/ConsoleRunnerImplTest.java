package org.pantsbuild.tools.junit.impl;

import com.google.common.base.Charsets;
import com.google.common.collect.Lists;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.PrintStream;
import java.io.UnsupportedEncodingException;
import java.util.List;
import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.Result;
import org.junit.runner.notification.RunListener;
import org.pantsbuild.tools.junit.lib.AllFailingTest;
import org.pantsbuild.tools.junit.lib.AllPassingTest;
import org.pantsbuild.tools.junit.lib.ExceptionInSetupTest;
import org.pantsbuild.tools.junit.lib.OutputModeTest;

import static org.hamcrest.CoreMatchers.containsString;
import static org.hamcrest.CoreMatchers.not;
import static org.hamcrest.MatcherAssert.assertThat;
import static org.junit.Assert.fail;

/**
 * These tests are similar to the tests in ConsoleRunnerTest but they create a ConosoleRunnerImpl
 * directory so they can capture the output more easily and test assertions based on the output.
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

  private String runTest(Class testClass) {
    return runTests(Lists.newArrayList(testClass.getCanonicalName()), false);
  }

  private String runTest(Class testClass, boolean shouldFail) {
    return runTests(Lists.newArrayList(testClass.getCanonicalName()), shouldFail);
  }

  private String runTests(List<String> tests, boolean shouldFail) {
    ByteArrayOutputStream outContent = new ByteArrayOutputStream();
    PrintStream outputStream = new PrintStream(outContent);

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
        System.err);

    try {
      runner.run(tests);
      if (shouldFail) {
        fail("Expected RuntimeException");
      }
    } catch (RuntimeException e) {
      if (!shouldFail) {
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
    String output = runTest(AllFailingTest.class, true);
    assertThat(output, containsString("There were 4 failures:"));
    assertThat(output, containsString("Tests run: 4,  Failures: 4"));

    failFast = true;
    output = runTest(AllFailingTest.class, true);
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("Tests run: 1,  Failures: 1"));
  }

  @Test
  public void testFailFastWithMultipleThreads() {
    failFast = false;
    parallelThreads = 8;
    String output = runTest(AllFailingTest.class, true);
    assertThat(output, containsString("There were 4 failures:"));
    assertThat(output, containsString("Tests run: 4,  Failures: 4"));

    failFast = true;
    parallelThreads = 8;
    output = runTest(AllFailingTest.class, true);
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("Tests run: 1,  Failures: 1"));
  }

  @Test
  public void testPerTestTimer() {
    perTestTimer = false;
    String output = runTest(AllPassingTest.class);
    assertThat(output, containsString("...."));
    assertThat(output, containsString("OK (4 tests)"));
    assertThat(output, not(containsString("AllPassingTest")));

    perTestTimer = true;
    output = runTest(AllPassingTest.class);

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
    String output = runTest(OutputModeTest.class, true);
    assertThat(output, containsString("There were 2 failures:"));
    assertThat(output, containsString("Output from passing test"));
    assertThat(output, containsString("Output from failing test"));
    assertThat(output, containsString("Output from error test"));
    assertThat(output, not(containsString("Output from ignored test")));
    assertThat(output, containsString("testFails(org.pantsbuild.tools.junit.lib.OutputModeTest)"));
    assertThat(output, containsString("testErrors(org.pantsbuild.tools.junit.lib.OutputModeTest)"));
    assertThat(output, containsString("Tests run: 3,  Failures: 2"));

    outputMode = ConsoleRunnerImpl.OutputMode.FAILURE_ONLY;
    output = runTest(OutputModeTest.class, true);
    assertThat(output, containsString("There were 2 failures:"));
    assertThat(output, not(containsString("Output from passing test")));
    assertThat(output, containsString("Output from failing test"));
    assertThat(output, containsString("Output from error test"));
    assertThat(output, not(containsString("Output from ignored test")));
    assertThat(output, containsString("testFails(org.pantsbuild.tools.junit.lib.OutputModeTest)"));
    assertThat(output, containsString("testErrors(org.pantsbuild.tools.junit.lib.OutputModeTest)"));
    assertThat(output, containsString("Tests run: 3,  Failures: 2"));

    outputMode = ConsoleRunnerImpl.OutputMode.NONE;
    output = runTest(OutputModeTest.class, true);
    assertThat(output, containsString("There were 2 failures:"));
    assertThat(output, not(containsString("Output from passing test")));
    assertThat(output, not(containsString("Output from failing test")));
    assertThat(output, not(containsString("Output from error test")));
    assertThat(output, not(containsString("Output from ignored test")));
    assertThat(output, containsString("testFails(org.pantsbuild.tools.junit.lib.OutputModeTest)"));
    assertThat(output, containsString("testErrors(org.pantsbuild.tools.junit.lib.OutputModeTest)"));
    assertThat(output, containsString("Tests run: 3,  Failures: 2"));
  }

  @Test
  public void testOutputModeExceptionInBefore() {
    outputMode = ConsoleRunnerImpl.OutputMode.ALL;
    String output = runTest(ExceptionInSetupTest.class, true);
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("java.lang.RuntimeException"));
    assertThat(output, containsString("Tests run: 0,  Failures: 1"));
    assertThat(output, not(containsString("Test mechanism")));

    outputMode = ConsoleRunnerImpl.OutputMode.FAILURE_ONLY;
    output = runTest(ExceptionInSetupTest.class, true);
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("java.lang.RuntimeException"));
    assertThat(output, containsString("Tests run: 0,  Failures: 1"));
    assertThat(output, not(containsString("Test mechanism")));

    outputMode = ConsoleRunnerImpl.OutputMode.NONE;
    output = runTest(ExceptionInSetupTest.class, true);
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("java.lang.RuntimeException"));
    assertThat(output, containsString("Tests run: 0,  Failures: 1"));
    assertThat(output, not(containsString("Test mechanism")));
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

    String output = runTest(AllPassingTest.class, true);
    assertThat(output, containsString("OK (4 tests)"));
    assertThat(output, containsString("java.io.IOException: Bogus IOException"));
  }
}
