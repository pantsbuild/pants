// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.PrintStream;
import java.util.List;
import org.apache.commons.io.FileUtils;
import org.hamcrest.CoreMatchers;
import org.junit.Assert;
import org.junit.Test;
import org.pantsbuild.tools.junit.ConsoleRunner;
import org.pantsbuild.tools.junit.lib.FailingTestRunner;
import org.pantsbuild.tools.junit.lib.FlakyTest;
import org.pantsbuild.tools.junit.lib.MockTest4;
import org.pantsbuild.tools.junit.lib.TestRegistry;
import org.pantsbuild.tools.junit.lib.XmlReportAllIgnoredTest;
import org.pantsbuild.tools.junit.lib.XmlReportAllPassingTest;
import org.pantsbuild.tools.junit.lib.XmlReportFailingParameterizedTest;
import org.pantsbuild.tools.junit.lib.XmlReportFailingTestRunnerTest;
import org.pantsbuild.tools.junit.lib.XmlReportFailInSetupTest;
import org.pantsbuild.tools.junit.lib.XmlReportFirstTestIngoredTest;
import org.pantsbuild.tools.junit.lib.XmlReportIgnoredTestSuiteTest;
import org.pantsbuild.tools.junit.lib.XmlReportTest;
import org.pantsbuild.tools.junit.lib.XmlReportTestSuite;

import static org.hamcrest.CoreMatchers.containsString;
import static org.hamcrest.CoreMatchers.not;
import static org.hamcrest.MatcherAssert.assertThat;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * Tests several recently added features in ConsoleRunner.
 * TODO: cover the rest of ConsoleRunner functionality.
 */
public class ConsoleRunnerTest extends ConsoleRunnerTestBase {
  @Test
  public void testNormalTesting() {
    ConsoleRunnerImpl.main(asArgsArray("MockTest1 MockTest2 MockTest3"));
    assertEquals("test11 test12 test13 test21 test22 test31 test32",
        TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting02() {
    ConsoleRunnerImpl.main(asArgsArray("MockTest1 MockTest2 MockTest3 -test-shard 0/2"));
    assertEquals("test11 test13 test22 test32", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting13() {
    ConsoleRunnerImpl.main(asArgsArray("MockTest1 MockTest2 MockTest3 -test-shard 1/3"));
    assertEquals("test12 test22", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting23() {
    // This tests a corner case when no tests from MockTest2 are going to run.
    ConsoleRunnerImpl.main(asArgsArray(
        "MockTest1 MockTest2 MockTest3 -test-shard 2/3"));
    assertEquals("test13 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting12WithParallelThreads() {
    ConsoleRunnerImpl.main(asArgsArray(
        "MockTest1 MockTest2 MockTest3 "
        + "-test-shard 1/2 -parallel-threads 4 -default-concurrency PARALLEL_CLASSES"));
    assertEquals("test12 test21 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting23WithParallelThreads() {
    // This tests a corner case when no tests from MockTest2 are going to run.
    ConsoleRunnerImpl.main(asArgsArray(
        "MockTest1 MockTest2 MockTest3 "
        + "-test-shard 2/3 -parallel-threads 3 -default-concurrency PARALLEL_CLASSES"));
    assertEquals("test13 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testFlakyTests() {
    FlakyTest.numFlakyTestInstantiations = 0;
    FlakyTest.numExpectedExceptionMethodInvocations = 0;

    try {
      ConsoleRunnerImpl.main(asArgsArray("FlakyTest -num-retries 2"));
      fail("Should have failed with RuntimeException due to FlakyTest.methodAlwaysFails");
      // FlakyTest.methodAlwaysFails fails this way - though perhaps that should be fixed to be an
      // RTE subclass.
    } catch (RuntimeException ex) {
      // Expected due to FlakyTest.methodAlwaysFails()
    }

    assertEquals("expected_ex flaky1 flaky1 flaky2 flaky2 flaky2 flaky3 flaky3 flaky3 "
        + "notflaky", TestRegistry.getCalledTests());

    // Verify that FlakyTest class has been instantiated once per test method invocation,
    // including flaky test method invocations.
    assertEquals(10, FlakyTest.numFlakyTestInstantiations);

    // Verify that a method with expected exception is not treated
    // as flaky - that is, it should be invoked only once.
    assertEquals(1, FlakyTest.numExpectedExceptionMethodInvocations);
  }

  @Test
  public void testTestCase() {
    ConsoleRunnerImpl.main(asArgsArray("SimpleTestCase"));
    assertEquals("testDummy", TestRegistry.getCalledTests());
  }

  @Test
  public void testConsoleOutput() {
    ByteArrayOutputStream outContent = new ByteArrayOutputStream();
    PrintStream stdout = System.out;
    PrintStream stderr = System.err;
    try {
      System.setOut(new PrintStream(outContent));
      System.setErr(new PrintStream(new ByteArrayOutputStream()));

      ConsoleRunnerImpl.main(asArgsArray("MockTest4 -parallel-threads 1 -xmlreport"));
      Assert.assertEquals("test41 test42", TestRegistry.getCalledTests());
      String output = outContent.toString();
      assertThat(output, CoreMatchers.containsString("test41"));
      assertThat(output, CoreMatchers.containsString("start test42"));
      assertThat(output, CoreMatchers.containsString("end test42"));
    } finally {
      System.setOut(stdout);
      System.setErr(stderr);
    }
  }

  @Test
  public void testOutputDir() throws Exception {
    String outdir = temporary.newFolder("testOutputDir").getAbsolutePath();
    ConsoleRunnerImpl.main(asArgsArray(
        "MockTest4 -parallel-threads 1 -default-concurrency PARALLEL_CLASSES -xmlreport -outdir "
            + outdir));
    Assert.assertEquals("test41 test42", TestRegistry.getCalledTests());

    String testClassName = MockTest4.class.getCanonicalName();
    String output = FileUtils.readFileToString(new File(outdir, testClassName + ".out.txt"));
    assertThat(output, CoreMatchers.containsString("test41"));
    assertThat(output, CoreMatchers.containsString("start test42"));
    assertThat(output, CoreMatchers.containsString("end test42"));
  }

  @Test
  public void testParallelAnnotation() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray(
      "AnnotatedParallelTest1 AnnotatedParallelTest2 -parallel-threads 2"));
    assertEquals("aptest1 aptest2", TestRegistry.getCalledTests());
  }

  @Test
  public void testSerialAnnotation() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray(
        "AnnotatedSerialTest1 AnnotatedSerialTest2 "
        + "-default-concurrency PARALLEL_CLASSES -parallel-threads 2"));
    assertEquals("astest1 astest2", TestRegistry.getCalledTests());
  }

  /* LEGACY, remove after -default-parallel argument is removed */
  @Test
  public void testParallelDefaultParallel() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray(
        "ParallelTest1 ParallelTest2 -parallel-threads 2 -default-parallel"));
    assertEquals("ptest1 ptest2", TestRegistry.getCalledTests());
  }

  /* LEGACY, remove after -parallel-methods argument is removed */
  @Test
  public void testParallelMethodsDefaultParallel() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray(
        "ParallelMethodsDefaultParallelTest1 ParallelMethodsDefaultParallelTest2"
            + " -parallel-methods -parallel-threads 4 -default-parallel"));
    assertEquals("pmdptest11 pmdptest12 pmdptest21 pmdptest22", TestRegistry.getCalledTests());
  }

  @Test
  public void testConcurrencyParallelClasses() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray(
        "ParallelTest1 ParallelTest2 -parallel-threads 2 -default-concurrency PARALLEL_CLASSES"));
    assertEquals("ptest1 ptest2", TestRegistry.getCalledTests());
  }

  @Test
  public void testConcurrencyParallelBoth() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray(
        "ParallelMethodsDefaultParallelTest1 ParallelMethodsDefaultParallelTest2"
            + " -default-concurrency PARALLEL_BOTH -parallel-threads 4"));
    assertEquals("pmdptest11 pmdptest12 pmdptest21 pmdptest22", TestRegistry.getCalledTests());
  }

  @Test
  public void testConcurrencySerial() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray(
        "SerialTest1 SerialTest2"
            + " -default-concurrency SERIAL -parallel-threads 4"));
    assertEquals("stest1 stest2", TestRegistry.getCalledTests());

  }

  @Test
  public void testXmlReportAll() throws Exception {
    String testClassName = XmlReportTest.class.getCanonicalName();

    AntJunitXmlReportListener.TestSuite testSuite = runTestAndParseXml(testClassName, true);

    assertNotNull(testSuite);
    assertEquals(4, testSuite.getTests());
    assertEquals(1, testSuite.getFailures());
    assertEquals(1, testSuite.getErrors());
    assertEquals(1, testSuite.getSkipped());
    assertTrue(Float.parseFloat(testSuite.getTime()) > 0);
    assertEquals(testClassName, testSuite.getName());
    assertEquals("Test output\n", testSuite.getOut());
    assertEquals("", testSuite.getErr());

    List<AntJunitXmlReportListener.TestCase> testCases = testSuite.getTestCases();
    assertEquals(4, testCases.size());
    sortTestCasesByName(testCases);

    AntJunitXmlReportListener.TestCase errorTestCase = testCases.get(0);
    assertEquals(testClassName, errorTestCase.getClassname());
    assertEquals("testXmlErrors", errorTestCase.getName());
    assertTrue(Float.parseFloat(errorTestCase.getTime()) > 0);
    assertNull(errorTestCase.getFailure());
    assertEquals("testXmlErrors exception", errorTestCase.getError().getMessage());
    assertEquals("java.lang.Exception", errorTestCase.getError().getType());
    assertThat(errorTestCase.getError().getStacktrace(),
        containsString(testClassName + ".testXmlErrors("));

    AntJunitXmlReportListener.TestCase failureTestCase = testCases.get(1);
    assertEquals(testClassName, failureTestCase.getClassname());
    assertEquals("testXmlFails", failureTestCase.getName());
    assertTrue(Float.parseFloat(failureTestCase.getTime()) > 0);
    assertNull(failureTestCase.getError());
    assertEquals("java.lang.AssertionError", failureTestCase.getFailure().getType());
    assertThat(failureTestCase.getFailure().getStacktrace(),
        containsString(testClassName + ".testXmlFails("));

    AntJunitXmlReportListener.TestCase passingTestCase = testCases.get(2);
    assertEquals(testClassName, passingTestCase.getClassname());
    assertEquals("testXmlPasses", passingTestCase.getName());
    assertTrue(Float.parseFloat(passingTestCase.getTime()) > 0);
    assertNull(passingTestCase.getFailure());
    assertNull(passingTestCase.getError());

    AntJunitXmlReportListener.TestCase ignoredTestCase = testCases.get(3);
    assertEquals(testClassName, ignoredTestCase.getClassname());
    assertEquals("testXmlSkipped", ignoredTestCase.getName());
    assertEquals("0", ignoredTestCase.getTime());
    assertNull(ignoredTestCase.getFailure());
    assertNull(ignoredTestCase.getError());
  }

  @Test
  public void testXmlReportAllIgnored() throws Exception {
    String testClassName = XmlReportAllIgnoredTest.class.getCanonicalName();
    AntJunitXmlReportListener.TestSuite testSuite = runTestAndParseXml(testClassName, false);

    assertNotNull(testSuite);
    assertEquals(2, testSuite.getTests());
    assertEquals(0, testSuite.getFailures());
    assertEquals(0, testSuite.getErrors());
    assertEquals(2, testSuite.getSkipped());
    assertEquals("0", testSuite.getTime());
    assertEquals(testClassName, testSuite.getName());
  }

  @Test
  public void testXmlReportFirstTestIgnored() throws Exception {
    String testClassName = XmlReportFirstTestIngoredTest.class.getCanonicalName();
    AntJunitXmlReportListener.TestSuite testSuite = runTestAndParseXml(testClassName, false);

    assertNotNull(testSuite);
    assertEquals(2, testSuite.getTests());
    assertEquals(0, testSuite.getFailures());
    assertEquals(0, testSuite.getErrors());
    assertEquals(1, testSuite.getSkipped());
    assertTrue(Float.parseFloat(testSuite.getTime()) > 0);
    assertEquals(testClassName, testSuite.getName());
  }

  @Test
  public void testXmlReportAllPassing() throws Exception {
    String testClassName = XmlReportAllPassingTest.class.getCanonicalName();
    AntJunitXmlReportListener.TestSuite testSuite = runTestAndParseXml(testClassName, false);

    assertNotNull(testSuite);
    assertEquals(2, testSuite.getTests());
    assertEquals(0, testSuite.getFailures());
    assertEquals(0, testSuite.getErrors());
    assertEquals(0, testSuite.getSkipped());
    assertTrue(Float.parseFloat(testSuite.getTime()) > 0);
    assertEquals(testClassName, testSuite.getName());
  }

  @Test
  public void testXmlReportXmlElements() throws Exception {
    String testClassName = XmlReportAllPassingTest.class.getCanonicalName();
    String xmlOutput = FileUtils.readFileToString(runTestAndReturnXmlFile(testClassName, false));

    assertThat(xmlOutput, containsString("<testsuite"));
    assertThat(xmlOutput, containsString("<properties>"));
    assertThat(xmlOutput, containsString("<testcase"));
    assertThat(xmlOutput, containsString("<system-out>"));
    assertThat(xmlOutput, containsString("<system-err>"));
    assertThat(xmlOutput, not(containsString("startNs")));
    assertThat(xmlOutput, not(containsString("testClass")));
  }

  @Test
  public void testXmlReportFailInSetup() throws Exception {
    String testClassName = XmlReportFailInSetupTest.class.getCanonicalName();

    AntJunitXmlReportListener.TestSuite testSuite = runTestAndParseXml(testClassName, true);

    assertNotNull(testSuite);
    assertEquals(2, testSuite.getTests());
    assertEquals(0, testSuite.getFailures());
    assertEquals(2, testSuite.getErrors());
    assertEquals(0, testSuite.getSkipped());
    assertTrue(Float.parseFloat(testSuite.getTime()) > 0);
    assertEquals(testClassName, testSuite.getName());
  }

  @Test
  public void testXmlReportIgnoredTestSuite() throws Exception {
    String testClassName = XmlReportIgnoredTestSuiteTest.class.getCanonicalName();

    AntJunitXmlReportListener.TestSuite testSuite = runTestAndParseXml(testClassName, false);

    assertNotNull(testSuite);
    assertEquals(1, testSuite.getTests());
    assertEquals(0, testSuite.getFailures());
    assertEquals(0, testSuite.getErrors());
    assertEquals(1, testSuite.getSkipped());
    assertEquals("0", testSuite.getTime());
    assertEquals(testClassName, testSuite.getName());

    List<AntJunitXmlReportListener.TestCase> testCases = testSuite.getTestCases();
    assertEquals(1, testCases.size());

    AntJunitXmlReportListener.TestCase testCase = testCases.get(0);
    assertEquals(testClassName, testCase.getClassname());
    assertEquals(testClassName, testCase.getName());
    assertEquals("0", testCase.getTime());
    assertNull(testCase.getError());
    assertNull(testCase.getFailure());
  }

  @Test
  public void testXmlReportTestSuite() throws Exception {
    String testClassName = XmlReportTestSuite.class.getCanonicalName();

    File testXmlFile = runTestAndReturnXmlFile(testClassName, true);

    // With a test suite we get back TEST-*.xml files for the test classes
    // in the suite, not for the test suite class itself
    testXmlFile = new File(testXmlFile.getParent(),
        "TEST-" + XmlReportTest.class.getCanonicalName() + ".xml");
    AntJunitXmlReportListener.TestSuite testSuite = parseTestXml(testXmlFile);

    assertNotNull(testSuite);
    assertEquals(4, testSuite.getTests());
    assertEquals(1, testSuite.getFailures());
    assertEquals(1, testSuite.getErrors());
    assertEquals(1, testSuite.getSkipped());

    testXmlFile = new File(testXmlFile.getParent(),
        "TEST-" + XmlReportAllPassingTest.class.getCanonicalName() + ".xml");
    testSuite = parseTestXml(testXmlFile);
    assertNotNull(testSuite);
    assertEquals(2, testSuite.getTests());
    assertEquals(0, testSuite.getFailures());
    assertEquals(0, testSuite.getErrors());
    assertEquals(0, testSuite.getSkipped());
  }

  @Test
  public void testXmlReportFailingParameterizedTest() throws Exception {
    String testClassName = XmlReportFailingParameterizedTest.class.getCanonicalName();

    AntJunitXmlReportListener.TestSuite testSuite = runTestAndParseXml(testClassName, true);

    assertNotNull(testSuite);
    assertEquals(4, testSuite.getTests());
    assertEquals(1, testSuite.getFailures());
    assertEquals(2, testSuite.getErrors());
    assertEquals(0, testSuite.getSkipped());
    assertTrue(Float.parseFloat(testSuite.getTime()) > 0);
    assertEquals(testClassName, testSuite.getName());

    List<AntJunitXmlReportListener.TestCase> testCases = testSuite.getTestCases();
    assertEquals(4, testCases.size());
  }

  @Test
  public void testXmlErrorInTestRunnerInitialization() throws Exception {
    String testClassName = XmlReportFailingTestRunnerTest.class.getCanonicalName();

    AntJunitXmlReportListener.TestSuite testSuite = runTestAndParseXml(testClassName, true);

    assertNotNull(testSuite);
    assertEquals(1, testSuite.getTests());
    assertEquals(0, testSuite.getFailures());
    assertEquals(1, testSuite.getErrors());
    assertEquals(0, testSuite.getSkipped());
    assertEquals("0", testSuite.getTime());
    assertEquals(testClassName, testSuite.getName());

    List<AntJunitXmlReportListener.TestCase> testCases = testSuite.getTestCases();
    assertEquals(1, testCases.size());

    AntJunitXmlReportListener.TestCase testCase = testCases.get(0);
    assertEquals(testClassName, testCase.getClassname());
    assertEquals(testClassName, testCase.getName());
    assertEquals("0", testCase.getTime());
    assertNull(testCase.getFailure());
    assertEquals("failed in getTestRules", testCase.getError().getMessage());
    assertEquals("java.lang.RuntimeException", testCase.getError().getType());
    assertThat(testCase.getError().getStacktrace(),
        containsString(FailingTestRunner.class.getCanonicalName() + ".getTestRules("));
  }

  @Test
  public void testLegacyConcurrencyOptions() {
    // New style option overrides old
    assertEquals(Concurrency.SERIAL,
        ConsoleRunnerImpl.computeConcurrencyOption(Concurrency.SERIAL, true, true));
    assertEquals(Concurrency.PARALLEL_CLASSES,
        ConsoleRunnerImpl.computeConcurrencyOption(Concurrency.PARALLEL_CLASSES, false, false));

    assertEquals(Concurrency.SERIAL,
        ConsoleRunnerImpl.computeConcurrencyOption(null, false, false));
    assertEquals(Concurrency.SERIAL,
        ConsoleRunnerImpl.computeConcurrencyOption(null, false, true));
    assertEquals(Concurrency.PARALLEL_BOTH,
        ConsoleRunnerImpl.computeConcurrencyOption(null, true, true));
    assertEquals(Concurrency.PARALLEL_CLASSES,
        ConsoleRunnerImpl.computeConcurrencyOption(null, true, false));
  }
}
