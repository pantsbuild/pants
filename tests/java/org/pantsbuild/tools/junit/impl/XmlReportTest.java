// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import com.google.common.base.Charsets;
import com.google.common.base.Joiner;
import java.io.File;
import java.io.IOException;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import javax.xml.bind.JAXBContext;
import javax.xml.bind.JAXBException;
import javax.xml.bind.Unmarshaller;
import org.apache.commons.io.FileUtils;
import org.junit.Test;
import org.pantsbuild.tools.junit.lib.ConsoleRunnerTestBase;
import org.pantsbuild.tools.junit.lib.FailingTestRunner;
import org.pantsbuild.tools.junit.lib.XmlReportAllIgnoredTest;
import org.pantsbuild.tools.junit.lib.XmlReportAllPassingTest;
import org.pantsbuild.tools.junit.lib.XmlReportAssumeSetupTest;
import org.pantsbuild.tools.junit.lib.XmlReportAssumeTest;
import org.pantsbuild.tools.junit.lib.XmlReportFailInSetupTest;
import org.pantsbuild.tools.junit.lib.XmlReportFailingParameterizedTest;
import org.pantsbuild.tools.junit.lib.XmlReportFailingTestRunnerTest;
import org.pantsbuild.tools.junit.lib.XmlReportFirstTestIngoredTest;
import org.pantsbuild.tools.junit.lib.XmlReportIgnoredTestSuiteTest;
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
 * Test the XML report output.
 */
public class XmlReportTest extends ConsoleRunnerTestBase {

  /**
   * <P>This test is Parameterized to run with different combinations of
   * -default-concurrency and -use-experimental-runner flags.
   * </P>
   * <P>
   * See {@link ConsoleRunnerTestBase#invokeConsoleRunner(String)}
   * </P>
   */
  public XmlReportTest(TestParameters parameters) {
    super(parameters);
  }

  @Test
  public void testXmlReportAll() throws Exception {
    String testClassName = org.pantsbuild.tools.junit.lib.XmlReportTest.class.getCanonicalName();

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
  public void testXmlReportAssume() throws Exception {
    String testClassName = XmlReportAssumeTest.class.getCanonicalName();
    AntJunitXmlReportListener.TestSuite testSuite = runTestAndParseXml(testClassName, true);

    assertNotNull(testSuite);
    assertEquals(3, testSuite.getTests());
    assertEquals(1, testSuite.getFailures());
    assertEquals(0, testSuite.getErrors());
    assertEquals(1, testSuite.getSkipped());
    assertTrue(Float.parseFloat(testSuite.getTime()) > 0);
    assertEquals(testClassName, testSuite.getName());
  }

  @Test
  public void testXmlReportAssumeInSetup() throws Exception {
    String testClassName = XmlReportAssumeSetupTest.class.getCanonicalName();
    AntJunitXmlReportListener.TestSuite testSuite = runTestAndParseXml(testClassName, false);

    assertNotNull(testSuite);
    assertEquals(2, testSuite.getTests());
    assertEquals(0, testSuite.getFailures());
    assertEquals(0, testSuite.getErrors());
    assertEquals(2, testSuite.getSkipped());
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
    String xmlOutput = FileUtils.readFileToString(
        runTestAndReturnXmlFile(testClassName, false), Charsets.UTF_8);

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
        "TEST-" + org.pantsbuild.tools.junit.lib.XmlReportTest.class.getCanonicalName() + ".xml");
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
    assertThat(testCase.getError().getMessage(), containsString("failed in getTestRules"));
    assertEquals("java.lang.RuntimeException", testCase.getError().getType());
    assertThat(testCase.getError().getStacktrace(),
        containsString(FailingTestRunner.class.getCanonicalName() + ".getTestRules("));
  }

  protected File runTestAndReturnXmlFile(String testClassName, boolean shouldFail)
      throws IOException, JAXBException {
    String outdirPath = temporary.newFolder("testOutputDir").getAbsolutePath();

    String args = Joiner.on(" ").join(testClassName, "-xmlreport", "-outdir", outdirPath);
    // run through asArgsArray so that we always tack on parameterized test arguments
    if (shouldFail) {
      try {
        invokeConsoleRunner(args);
        fail("The ConsoleRunner should throw an exception when running these tests");
      } catch (RuntimeException ex) {
        // Expected
        ex.printStackTrace();
      }
    } else {
      invokeConsoleRunner(args);
    }

    return new File(outdirPath, "TEST-" + testClassName + ".xml");
  }

  protected AntJunitXmlReportListener.TestSuite runTestAndParseXml(
      String testClassName, boolean shouldFail) throws IOException, JAXBException {
    return parseTestXml(runTestAndReturnXmlFile(testClassName, shouldFail));
  }

  protected AntJunitXmlReportListener.TestSuite parseTestXml(File testXmlFile)
      throws IOException, JAXBException {
    JAXBContext jaxbContext = JAXBContext.newInstance(AntJunitXmlReportListener.TestSuite.class);

    Unmarshaller jaxbUnmarshaller = jaxbContext.createUnmarshaller();
    return (AntJunitXmlReportListener.TestSuite) jaxbUnmarshaller.unmarshal(testXmlFile);
  }

  protected void sortTestCasesByName(List<AntJunitXmlReportListener.TestCase> testCases) {
    Collections.sort(testCases, new Comparator<AntJunitXmlReportListener.TestCase>() {
      public int compare(AntJunitXmlReportListener.TestCase tc1,
          AntJunitXmlReportListener.TestCase tc2) {
        return tc1.getName().compareTo(tc2.getName());
      }
    });
  }
}
