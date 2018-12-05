// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import com.google.common.base.Charsets;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;

import org.junit.Test;
import org.junit.runner.Result;
import org.junit.runner.notification.RunListener;
import org.pantsbuild.tools.junit.impl.security.JunitSecurityManagerConfig;
import org.pantsbuild.tools.junit.lib.AllFailingTest;
import org.pantsbuild.tools.junit.lib.AllIgnoredTest;
import org.pantsbuild.tools.junit.lib.AllPassingTest;
import org.pantsbuild.tools.junit.lib.ExceptionInSetupTest;
import org.pantsbuild.tools.junit.lib.LogOutputInTeardownTest;
import org.pantsbuild.tools.junit.lib.OutputModeTest;
import org.pantsbuild.tools.junit.lib.SystemExitsInObjectBody;
import org.pantsbuild.tools.junit.lib.security.network.BoundaryNetworkTests;
import org.pantsbuild.tools.junit.lib.security.sysexit.BeforeClassSysExitTestCase;
import org.pantsbuild.tools.junit.lib.security.sysexit.BoundarySystemExitTests;
import org.pantsbuild.tools.junit.lib.security.threads.DanglingThreadFromTestCase;
import org.pantsbuild.tools.junit.lib.security.sysexit.StaticSysExitTestCase;
import org.pantsbuild.tools.junit.lib.security.threads.ThreadStartedInBeforeClassAndJoinedAfterTest;
import org.pantsbuild.tools.junit.lib.security.threads.ThreadStartedInBeforeClassAndNotJoinedAfterTest;
import org.pantsbuild.tools.junit.lib.security.threads.ThreadStartedInBeforeTest;
import org.pantsbuild.tools.junit.lib.XmlReportTest;
import org.pantsbuild.tools.junit.lib.XmlReportTestSuite;

import static org.hamcrest.CoreMatchers.containsString;
import static org.hamcrest.CoreMatchers.not;
import static org.hamcrest.MatcherAssert.assertThat;
import static org.hamcrest.core.Is.is;
import static org.junit.Assert.fail;
import static org.pantsbuild.tools.junit.impl.security.JunitSecurityManagerConfig.*;

/**
 * These tests are similar to the tests in ConsoleRunnerTest but they create a ConosoleRunnerImpl
 * directory so they can capture and make assertions on the output.
 */
public class ConsoleRunnerImplTest extends ConsoleRunnerImplTestSetup {

  @Test
  public void testFailFast() {
    failFast = false;
    String output = runTestExpectingFailure(AllFailingTest.class);
    assertThat(output, containsString("There were 4 failures:"));
    assertThat(output, containsString("Tests run: 4,  Failures: 4"));

    failFast = true;
    output = runTestExpectingFailure(AllFailingTest.class);
    assertThat(output, containsString("There was 1 failure:"));
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
}
