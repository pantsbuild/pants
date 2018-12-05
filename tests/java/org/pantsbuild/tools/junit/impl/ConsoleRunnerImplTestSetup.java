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
import java.util.List;

import com.google.common.base.Charsets;
import com.google.common.collect.Lists;

import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.notification.StoppedByUserException;
import org.pantsbuild.tools.junit.impl.security.JunitSecViolationReportingManager;
import org.pantsbuild.tools.junit.impl.security.JunitSecurityManagerConfig;

import static org.junit.Assert.fail;
import static org.pantsbuild.tools.junit.impl.security.JunitSecurityManagerConfig.NetworkHandling;
import static org.pantsbuild.tools.junit.impl.security.JunitSecurityManagerConfig.SystemExitHandling;
import static org.pantsbuild.tools.junit.impl.security.JunitSecurityManagerConfig.ThreadHandling;

/**
 * These tests are similar to the tests in ConsoleRunnerTest but they create a ConosoleRunnerImpl
 * directory so they can capture and make assertions on the output.
 */
public class ConsoleRunnerImplTestSetup {

  @Rule
  public TemporaryFolder temporary = new TemporaryFolder();

  protected boolean failFast;
  protected ConsoleRunnerImpl.OutputMode outputMode;
  protected boolean xmlReport;
  protected File outdir;
  protected boolean perTestTimer;
  protected Concurrency defaultConcurrency;
  protected int parallelThreads;
  protected int testShard;
  protected int numTestShards;
  protected int numRetries;
  protected boolean useExperimentalRunner;

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

  String runTestExpectingSuccess(Class testClass) {
    JunitSecurityManagerConfig securityConfig = new JunitSecurityManagerConfig(
        SystemExitHandling.disallow,
        ThreadHandling.disallowLeakingTestCaseThreads,
        NetworkHandling.allowAll);
    return runTests(
        Lists.newArrayList(testClass.getCanonicalName()),
        false,
        securityConfig);
  }

  String runTestExpectingFailure(Class<?> testClass) {
    JunitSecurityManagerConfig securityConfig = new JunitSecurityManagerConfig(
        SystemExitHandling.disallow,
        ThreadHandling.disallowLeakingTestCaseThreads,
        NetworkHandling.allowAll);
    return runTests(
        Lists.newArrayList(testClass.getCanonicalName()),
        true,
        securityConfig);
  }

  protected String runTestsExpectingSuccess(
      JunitSecurityManagerConfig secMgrConfig,
      Class<?> testClass
  ) {
    return runTests(
        Lists.newArrayList(testClass.getCanonicalName()),
        false,
        secMgrConfig);
  }

  protected String runTestsExpectingFailure(
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

  private JunitSecurityManagerConfig configDisallowingSystemExitButAllowingEverythingElse() {
    return new JunitSecurityManagerConfig(
        SystemExitHandling.disallow,
        ThreadHandling.allowAll,
        NetworkHandling.allowAll);
  }

  String getTestLogContents(Class testClass, String extension) {
    try {
      return new String(
          Files.readAllBytes(Paths.get(outdir.getPath(), testClass.getCanonicalName() + extension)),
          Charsets.UTF_8);
    } catch (IOException e) {
      throw new RuntimeException(e);
    }
  }
}
