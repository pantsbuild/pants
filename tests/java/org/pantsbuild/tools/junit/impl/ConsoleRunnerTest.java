// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.util.List;
import org.apache.commons.io.FileUtils;
import org.junit.Test;

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
public class ConsoleRunnerTest extends ConsoleRunnerTestHelper {
  @Test
  public void testNormalTesting() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray("MockTest1 MockTest2 MockTest3"));
    assertEquals("test11 test12 test13 test21 test22 test31 test32",
        TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting02() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray("MockTest1 MockTest2 MockTest3 -test-shard 0/2"));
    assertEquals("test11 test13 test22 test32", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting13() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray("MockTest1 MockTest2 MockTest3 -test-shard 1/3"));
    assertEquals("test12 test22", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting23() throws Exception {
    // This tests a corner case when no tests from MockTest2 are going to run.
    ConsoleRunnerImpl.main(asArgsArray(
        "MockTest1 MockTest2 MockTest3 -test-shard 2/3"));
    assertEquals("test13 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting12WithParallelThreads() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray(
        "MockTest1 MockTest2 MockTest3 -test-shard 1/2 -parallel-threads 4 -default-parallel"));
    assertEquals("test12 test21 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting23WithParallelThreads() throws Exception {
    // This tests a corner case when no tests from MockTest2 are going to run.
    ConsoleRunnerImpl.main(asArgsArray(
        "MockTest1 MockTest2 MockTest3 -test-shard 2/3 -parallel-threads 3 -default-parallel"));
    assertEquals("test13 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testFlakyTests() throws Exception {
    FlakyTest.numFlakyTestInstantiations = 0;
    FlakyTest.numExpectedExceptionMethodInvocations = 0;

    try {
      FlakyTest.flakyTestsShouldFail = true;
      ConsoleRunnerImpl.main(asArgsArray("FlakyTest -num-retries 2"));
      fail("Should have failed with RuntimeException due to FlakyTest.methodAlwaysFails");
      // FlakyTest.methodAlwaysFails fails this way - though perhaps that should be fixed to be an
      // RTE subclass.
      // SUPPRESS CHECKSTYLE RegexpSinglelineJava
    } catch (RuntimeException ex) {
      // Expected due to FlakyTest.methodAlwaysFails()
    } finally {
      FlakyTest.flakyTestsShouldFail = false;
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
  public void testTestCase() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray("SimpleTestCase"));
    assertEquals("testDummy", TestRegistry.getCalledTests());
  }

  @Test
  public void testXmlReportAll() throws Exception {
    String testClassName = XmlReportTest.class.getCanonicalName();

    XmlReportTest.failingTestsShouldFail = true;
    AntJunitXmlReportListener.TestSuite testSuite = runTestAndParseXml(testClassName, true);
    XmlReportTest.failingTestsShouldFail = false;

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

    XmlReportFailInSetupTest.shouldFailDuringSetup = true;
    AntJunitXmlReportListener.TestSuite testSuite = runTestAndParseXml(testClassName, true);
    XmlReportFailInSetupTest.shouldFailDuringSetup = false;

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
  public void testXmlFailInCustomTestRunner() throws Exception {
    String testClassName = XmlReportCustomTestRunnerTest.class.getCanonicalName();

    CustomTestRunner.shouldFailDuringInitialization = true;
    AntJunitXmlReportListener.TestSuite testSuite = runTestAndParseXml(testClassName, true);
    CustomTestRunner.shouldFailDuringInitialization = false;

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
        containsString(CustomTestRunner.class.getCanonicalName() + ".getTestRules("));
  }
}
