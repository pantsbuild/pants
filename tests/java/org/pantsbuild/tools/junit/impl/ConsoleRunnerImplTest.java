// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import com.google.common.base.Charsets;
import com.google.common.collect.Lists;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.PrintStream;
import java.io.UnsupportedEncodingException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;
import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.Result;
import org.junit.runner.notification.RunListener;
import org.junit.runner.notification.StoppedByUserException;
import org.pantsbuild.tools.junit.impl.security.JunitSecViolationReportingManager;
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
    JunitSecurityManagerConfig securityConfig = new JunitSecurityManagerConfig(
        SystemExitHandling.disallow,
        ThreadHandling.disallowLeakingTestCaseThreads,
        NetworkHandling.allowAll);
    return runTests(
        Lists.newArrayList(testClass.getCanonicalName()),
        false,
        securityConfig);
  }

  private String runTestExpectingFailure(Class<?> testClass) {
    JunitSecurityManagerConfig securityConfig = new JunitSecurityManagerConfig(
        SystemExitHandling.disallow,
        ThreadHandling.disallowLeakingTestCaseThreads,
        NetworkHandling.allowAll);
    return runTests(
        Lists.newArrayList(testClass.getCanonicalName()),
        true,
        securityConfig);
  }

  private String runTestsExpectingSuccess(
      JunitSecurityManagerConfig secMgrConfig,
      Class<?> testClass
  ) {
    return runTests(
        Lists.newArrayList(testClass.getCanonicalName()),
        false,
        secMgrConfig);
  }

  private String runTestsExpectingFailure(
      JunitSecurityManagerConfig secMgrConfig,
      Class<?> testClass) {
    return runTests(
        Lists.newArrayList(testClass.getCanonicalName()),
        true,
        secMgrConfig);
  }

  private String runTests(
      List<String> tests,
      boolean shouldFail,
      JunitSecurityManagerConfig config
  ) {
    PrintStream originalOut = System.out;
    PrintStream originalErr = System.err;

    ByteArrayOutputStream outContent = new ByteArrayOutputStream();
    PrintStream outputStream = new PrintStream(outContent, true);
    JunitSecViolationReportingManager securityManager =
        new JunitSecViolationReportingManager(config);
    try {
      System.setSecurityManager(securityManager);
      return createAndRunConsoleRunner(
          tests,
          shouldFail,
          originalOut,
          outContent,
          outputStream,
          securityManager
      );
    } finally {
      // there might be a better way to do this.
      waitForDanglingThreadsToFinish(originalErr, securityManager);

      System.setOut(originalOut);
      System.setErr(originalErr);

      System.setSecurityManager(null); // TODO disallow this, but allow here, could also
                                       // TODO add a reset button to the sec mgr
    }
  }

  private void waitForDanglingThreadsToFinish(
      PrintStream originalErr,
      JunitSecViolationReportingManager junitSecViolationReportingManager
  ) {
    if (junitSecViolationReportingManager.anyHasDanglingThreads()) {
      originalErr.println("had dangling threads, trying interrupt");
      junitSecViolationReportingManager.interruptDanglingThreads();
      if (junitSecViolationReportingManager.anyHasDanglingThreads()) {
        originalErr.println("there are still remaining threads, sleeping");
        try {
          Thread.sleep(100);
        } catch (InterruptedException e) {
          // ignore
        }
      }
    } else {
      originalErr.println("no remaining threads");
    }
  }

  private String createAndRunConsoleRunner(
      List<String> tests,
      boolean shouldFail,
      PrintStream originalOut,
      ByteArrayOutputStream outContent,
      PrintStream outputStream,
      JunitSecViolationReportingManager junitSecViolationReportingManager
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
        System.err, // TODO, if there's an error reported on system err, it doesn't show up in
                    // the test failures.
        junitSecViolationReportingManager);

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

  @Test
  public void testFailSystemExit() {
    Class<BoundarySystemExitTests> testClass = BoundarySystemExitTests.class;
    String output = runTestsExpectingFailure(
        configDisallowingSystemExitButAllowingEverythingElse(),
        testClass);
    String testClassName = testClass.getCanonicalName();

    assertThat(output, containsString(") directSystemExit(" + testClassName + ")"));
    assertThat(output, containsString(") catchesSystemExit(" + testClassName + ")"));
    assertThat(output, containsString(") exitInJoinedThread(" + testClassName + ")"));
    assertThat(output, containsString(") exitInNotJoinedThread(" + testClassName + ")"));

    assertThat(output, containsString("There were 4 failures:"));
    assertThat(output, containsString("Tests run: 5,  Failures: 4"));

    assertThat(
        output,
        containsString(
            ") directSystemExit(" + testClassName + ")\n" +
                "org.pantsbuild.junit.security.SecurityViolationException: " +
                "System.exit calls are not allowed.\n"));
    assertThat(
        output,
        containsString(
            "\tat java.lang.Runtime.exit(Runtime.java:107)\n" +
                "\tat java.lang.System.exit(System.java:971)\n" +
                "\tat " + testClassName + ".directSystemExit(" + testClass.getSimpleName() +
                ".java:43)"));
  }

  @Test
  public void testWhenDanglingThreadsAllowedPassOnThreadStartedInTestCase() {
    JunitSecurityManagerConfig secMgrConfig =
        configDisallowingSystemExitButAllowingEverythingElse();
    String output = runTestsExpectingSuccess(secMgrConfig, DanglingThreadFromTestCase.class);
    assertThat(output, containsString("OK (1 test)"));
  }

  @Test
  public void testDisallowDanglingThreadStartedInTestCase() {
    Class<?> testClass = DanglingThreadFromTestCase.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            SystemExitHandling.disallow,
            ThreadHandling.disallowLeakingTestCaseThreads,
            NetworkHandling.allowAll),
        testClass);
    String testClassName = testClass.getCanonicalName();
    assertThat(output, containsString("startedThread(" + testClassName + ")"));
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("Tests run: 1,  Failures: 1"));

    assertThat(output, containsString(") startedThread(" + testClassName + ")\n" +
        "org.pantsbuild.junit.security.SecurityViolationException: " +
        "Threads from startedThread(" + testClassName + ") are still running (1):\n" +
        "\t\tThread-"
    ));
  }

  @Test
  public void testThreadStartedInBeforeTestAndJoinedAfter() {
    // Expect that of the two tests, only the test that fails due to an assertion failure will fail.
    // And that it fails due to that failure
    Class<?> testClass = ThreadStartedInBeforeTest.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            SystemExitHandling.disallow,
            ThreadHandling.disallowLeakingTestCaseThreads,
            NetworkHandling.allowAll),
        testClass);
    assertThat(output, containsString("failing(" + testClass.getCanonicalName() + ")"));
    assertThat(output, containsString("java.lang.AssertionError: failing"));
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("Tests run: 2,  Failures: 1"));
  }

  @Test
  public void testThreadStartedInBeforeClassAndJoinedAfterClassWithPerSuiteThreadLife() {
    // Expect that of the two tests, only the test that fails due to an assertion failure will fail.
    // And that it fails due to that failure.
    // The other failure will be ascribed to the test class instead.
    Class<?> testClass = ThreadStartedInBeforeClassAndJoinedAfterTest.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            SystemExitHandling.disallow,
            ThreadHandling.disallowLeakingTestSuiteThreads,
            NetworkHandling.allowAll),
        testClass);
    assertThat(output, containsString("failing(" + testClass.getCanonicalName() + ")"));
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("Tests run: 2,  Failures: 1"));
  }

  @Test
  public void testThreadStartedInBeforeClassAndNotJoinedAfterClassWithPerSuiteThreadLife() {
    // Expect that of the two tests, only the test that fails due to an assertion failure will fail.
    // And that it fails due to that failure.
    // The other failure will be ascribed to the test class instead.
    Class<?> testClass = ThreadStartedInBeforeClassAndNotJoinedAfterTest.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            SystemExitHandling.disallow,
            ThreadHandling.disallowLeakingTestSuiteThreads,
            NetworkHandling.allowAll),
        testClass);

    assertThat(
        ThreadStartedInBeforeClassAndNotJoinedAfterTest.thread.getState(),
        is(Thread.State.WAITING));
    String testClassName = testClass.getCanonicalName();
    assertThat(output, containsString("failing(" + testClassName + ")"));

    assertThat(output, containsString("There were 2 failures:"));
    assertThat(output, containsString("Tests run: 2,  Failures: 2"));

    assertThat(output, containsString(") " + testClassName + "\n" +
        "org.pantsbuild.junit.security.SecurityViolationException: " +
        "Threads from " + testClassName + " are still running (1):\n" +
        "\t\tThread-"
    ));
    // stop thread waiting on the latch.
    ThreadStartedInBeforeClassAndNotJoinedAfterTest.latch.countDown();
  }

  @Test
  public void testSystemExitFromBodyOfScalaObject() {
    Class<?> testClass = SystemExitsInObjectBody.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            SystemExitHandling.disallow,
            ThreadHandling.disallowLeakingTestSuiteThreads,
            NetworkHandling.allowAll),
        testClass);


    String testClassName = testClass.getCanonicalName();

    assertThat(output, containsString(
        ") initializationError(" + testClassName + ")\n" +
            "java.lang.ExceptionInInitializerError\n" +
            "\tat " + testClassName + ".<init>(SystemExitsInObjectBody.scala:12)"));
    // NB This caused by clause is hard to find in the stacktrace right now, it might make sense to
    // unwrap the error and display it.
    assertThat(output, containsString(
        "Caused by: " +
            "org.pantsbuild.junit.security.SecurityViolationException: " +
            "System.exit calls are not allowed.\n"));
  }

  @Test
  public void treatStaticSystemExitAsFailure() {
    Class<?> testClass = StaticSysExitTestCase.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            SystemExitHandling.disallow,
            ThreadHandling.disallowLeakingTestCaseThreads,
            NetworkHandling.allowAll),
        testClass);

    assertThat(output, containsString("passingTest(" + testClass.getCanonicalName() + ")"));
    assertThat(output, containsString("System.exit calls are not allowed"));
    assertThat(output, containsString("There were 2 failures:"));
    assertThat(output, containsString("Tests run: 2,  Failures: 2"));
  }

  @Test
  public void treatBeforeClassSystemExitAsFailure() {
    Class<?> testClass = BeforeClassSysExitTestCase.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            SystemExitHandling.disallow,
            ThreadHandling.disallowLeakingTestCaseThreads,
            NetworkHandling.allowAll),
        testClass);

    assertThat(output, containsString("1) " + testClass.getCanonicalName() + ""));
    assertThat(output, containsString("System.exit calls are not allowed"));

    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("Tests run: 0,  Failures: 1"));
  }

  @Test
  public void testFailNetworkAccess() {
    Class<BoundaryNetworkTests> testClass = BoundaryNetworkTests.class;
    BoundaryNetworkTests.reset();
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            SystemExitHandling.disallow,
            ThreadHandling.allowAll,
            JunitSecurityManagerConfig.NetworkHandling.onlyLocalhost
        ),
        testClass);
    String testClassName = testClass.getCanonicalName();

    assertThat(output, containsString(") directNetworkCall(" + testClassName + ")"));
    assertThat(output, containsString(") catchesNetworkCall(" + testClassName + ")"));
    assertThat(output, containsString(") networkCallInJoinedThread(" + testClassName + ")"));
    assertThat(output, containsString(") networkCallInNotJoinedThread(" + testClassName + ")"));

    assertThat(output, containsString("There were 4 failures:"));
    assertThat(output, containsString("Tests run: 5,  Failures: 4"));

    assertThat(output, containsString(
        ") directNetworkCall(" + testClassName + ")\n" +
            "org.pantsbuild.junit.security.SecurityViolationException: " +
            "DNS request for example.com is not allowed.\n"));
    // ... some other ats
    assertThat(output, containsString(
        "\tat java.net.InetAddress.getAllByName0(InetAddress.java:1268)\n" +
            "\tat java.net.InetAddress.getAllByName(InetAddress.java:1192)\n" +
            "\tat java.net.InetAddress.getAllByName(InetAddress.java:1126)\n" +
            "\tat java.net.InetAddress.getByName(InetAddress.java:1076)\n" +
            "\tat java.net.InetSocketAddress.<init>(InetSocketAddress.java:220)\n" +
            "\tat " + testClassName + ".makeNetworkCall"));
  }

  @Test
  public void testAllowNetworkAccessForLocalhost() {
    Class<BoundaryNetworkTests> testClass = BoundaryNetworkTests.class;
    BoundaryNetworkTests.setHostname("localhost");
    String output = runTestsExpectingSuccess(
        new JunitSecurityManagerConfig(
            SystemExitHandling.disallow,
            ThreadHandling.allowAll,
            JunitSecurityManagerConfig.NetworkHandling.onlyLocalhost
        ),
        testClass);

    assertThat(output, containsString("OK (5 tests)\n"));
  }

  private JunitSecurityManagerConfig configDisallowingSystemExitButAllowingEverythingElse() {
    return new JunitSecurityManagerConfig(
        SystemExitHandling.disallow,
        ThreadHandling.allowAll,
        NetworkHandling.allowAll);
  }

  // TODO Consider recording where the thread was started and including that in the message
  // TODO handle various ways to say localhost
  // TODO look up host name and fail if it's not localhost
  // TODO scope checks
  // TODO assert that a fail fast does not trigger a security manager fail
  // TODO collapse common initialization errors in test runs.
  // TODO ensure that this has a clear error
  //   The question here is whether it should fail before running the tests. Right now it runs them,
  //   but the resulting error is
  //   java.lang.ExceptionInInitializerError
  //   at sun.reflect.NativeConstructorAccessorImpl.newInstance0(Native Method)
  //   ... 50 lines ...
  //   Caused by: java.lang.SecurityException: System.exit calls are not allowed.
  //   at org.pantsbuild.tools.junit.impl.security.JunitSecViolationReportingManager
  //   I think it should either end with 0 tests run 1 error, or
  //   2 run, 2 error, with a better error than ExceptionInInitializerError


  private String getTestLogContents(Class testClass, String extension) {
    try {
      return new String(
          Files.readAllBytes(Paths.get(outdir.getPath(), testClass.getCanonicalName() + extension)),
          Charsets.UTF_8);
    } catch (IOException e) {
      throw new RuntimeException(e);
    }
  }
}
