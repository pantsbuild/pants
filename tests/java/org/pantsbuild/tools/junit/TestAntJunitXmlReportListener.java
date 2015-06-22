package org.pantsbuild.tools.junit;

import java.io.File;
import java.io.IOException;
import org.junit.Test;
import org.junit.runner.Description;
import org.junit.runner.notification.Failure;
import org.pantsbuild.tools.junit.AntJunitXmlReportListener.UnknownFailureSuite;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

public class TestAntJunitXmlReportListener {

  // Used for creating Description instances
  class DummyTestSuite {
  }

  private AntJunitXmlReportListener newListener() throws Exception {
    File tempFile = File.createTempFile("testFailedExpected", ".xml");
    tempFile.deleteOnExit();
    StreamSource simulatedTestOutput = new StreamSource() {

      @Override public byte[] readOut(Class<?> testClass) throws IOException {
        return new byte[0];
      }

      @Override public byte[] readErr(Class<?> testClass) throws IOException {
        return new byte[0];
      }
    };
     return new AntJunitXmlReportListener(tempFile, simulatedTestOutput);
  }

  @Test
  public void testFailedExpected() throws Exception {
    AntJunitXmlReportListener listener = newListener();

    Description test1 = Description.createTestDescription(DummyTestSuite.class, "test1");
    listener.testStarted(test1);
    Exception ex = new Exception("Dummy Exception");
    Failure test1Failure = new Failure(test1, ex);
    listener.testFailure(test1Failure);

    assertEquals(1, listener.getSuites().size());
    AntJunitXmlReportListener.TestSuite suite = listener.getSuites().get(DummyTestSuite.class);
    assertEquals(suite.getErrors(), 1);
    assertEquals(suite.getFailures(), 0);

    assertEquals(1, listener.getCases().size());
    AntJunitXmlReportListener.TestCase testCase = listener.getCases().get(test1);
    assertEquals(testCase.getClassname(),
        "org.pantsbuild.tools.junit.TestAntJunitXmlReportListener$DummyTestSuite");
    assertNull(null, testCase.getFailure());
    assertEquals(ex.getMessage(), testCase.getError().getMessage());
  }

  @Test
  public void testFailedNoStarted_mechanism() throws Exception {
    AntJunitXmlReportListener listener = newListener();
    Exception ex = new Exception("Dummy Exception");
    Failure mechanismFailure = new Failure(Description.TEST_MECHANISM, ex);
    listener.testFailure(mechanismFailure);

    assertEquals(1, listener.getSuites().size());
    AntJunitXmlReportListener.TestSuite suite = listener.getSuites()
        .get(UnknownFailureSuite.class);
    assertEquals(suite.getErrors(), 0);
    assertEquals(suite.getFailures(), 1);

    assertEquals(1, listener.getCases().size());
    AntJunitXmlReportListener.TestCase testCase =
        listener.getCases().get(Description.TEST_MECHANISM);
    assertNull(null, testCase.getError());
    assertEquals(ex.getMessage(), testCase.getFailure().getMessage());
  }


  @Test
  public void testFailedNoStarted_other() throws Exception {
    AntJunitXmlReportListener listener = newListener();
    Exception ex = new Exception("Dummy Exception");
    Description suiteDescription = Description.createSuiteDescription("UninitializableTestClass");
    Failure suiteFailure = new Failure(suiteDescription, ex);
    listener.testFailure(suiteFailure);

    assertEquals(1, listener.getSuites().size());
    AntJunitXmlReportListener.TestSuite suite = listener.getSuites()
        .get(UnknownFailureSuite.class);
    assertEquals(suite.getErrors(), 0);
    assertEquals(suite.getFailures(), 1);

    assertEquals(1, listener.getCases().size());
    AntJunitXmlReportListener.TestCase testCase = listener.getCases().get(suiteDescription);
    assertNull(null, testCase.getError());
    assertEquals(ex.getMessage(), testCase.getFailure().getMessage());
  }
}
