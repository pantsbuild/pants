// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import com.google.common.annotations.VisibleForTesting;
import com.google.common.base.Charsets;
import com.google.common.base.Function;
import com.google.common.collect.Iterables;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import java.io.File;
import java.io.FileWriter;
import java.io.FilterWriter;
import java.io.IOException;
import java.io.Writer;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.Map.Entry;
import java.util.concurrent.TimeUnit;
import javax.xml.bind.JAXB;
import javax.xml.bind.annotation.XmlAccessType;
import javax.xml.bind.annotation.XmlAccessorType;
import javax.xml.bind.annotation.XmlAttribute;
import javax.xml.bind.annotation.XmlElement;
import javax.xml.bind.annotation.XmlElementRef;
import javax.xml.bind.annotation.XmlElementWrapper;
import javax.xml.bind.annotation.XmlRootElement;
import javax.xml.bind.annotation.XmlTransient;
import javax.xml.bind.annotation.XmlValue;
import org.junit.runner.Description;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;

/**
 * A run listener that creates ant junit xml report compatible output describing a junit run.
 */
class AntJunitXmlReportListener extends RunListener {

  /**
   * A JAXB bean describing a test case exception.  These may indicate either an assertion failure
   * or an uncaught test exception.
   */
  @XmlRootElement
  @XmlAccessorType(XmlAccessType.FIELD)
  static class Exception {
    @XmlAttribute private final String message;
    @XmlAttribute private final String type;
    @XmlValue private final String stacktrace;

    // for JAXB
    private Exception() {
      message = null;
      type = null;
      stacktrace = null;
    }

    Exception(Failure failure) {
      message = failure.getMessage();
      type = failure.getException().getClass().getName();
      stacktrace = failure.getTrace();
    }

    public String getMessage() {
      return message;
    }

    public String getType() {
      return type;
    }

    public String getStacktrace() {
      return stacktrace;
    }
  }

  /**
   * A JAXB bean describing an individual test method.
   */
  @XmlRootElement(name = "testcase")
  @XmlAccessorType(XmlAccessType.FIELD)
  static class TestCase {
    @XmlAttribute private final String classname;
    @XmlAttribute private final String name;
    @XmlAttribute private String time;
    @XmlElement private Exception failure;
    @XmlElement private Exception error;
    @XmlElement private String skipped;
    @XmlTransient private long startNs;

    // for JAXB
    private TestCase() {
      classname = null;
      name = null;
    }

    TestCase(Description test) {
      classname = test.getClassName();
      if (test.getMethodName() != null) {
        name = test.getMethodName();
      } else {
        name = test.getClassName();
      }
    }

    public String getClassname() {
      return classname;
    }

    public String getName() {
      return name;
    }

    public String getTime() {
      return time;
    }

    public Exception getFailure() {
      return failure;
    }

    public void setFailure(Exception failure) {
      this.failure = failure;
    }

    public Exception getError() {
      return error;
    }

    public void setError(Exception error) {
      this.error = error;
    }

    public String getSkipped() {
      return skipped;
    }

    public void setSkipped(boolean skipped) {
      if (skipped) {
        this.skipped = "";
        time = "0";
      } else {
        this.skipped = null;
        time = null;
      }
    }

    public void started() {
      startNs = System.nanoTime();
    }

    public void finished() {
      if (startNs != 0) {
        time = convertTimeSpanNs(System.nanoTime() - startNs);
      } else {
        time = "0";
      }
    }
  }

  /**
   * A JAXB bean describing an individual system property.
   */
  @XmlRootElement(name = "property")
  @XmlAccessorType(XmlAccessType.FIELD)
  static class Property {
    @XmlAttribute private final String name;
    @XmlAttribute private final String value;

    // for JAXB
    private Property() {
      name = null;
      value = null;
    }

    Property(String name, String value) {
      this.name = name;
      this.value = value;
    }

    public String getName() {
      return name;
    }

    public String getValue() {
      return value;
    }
  }

  /**
   * A JAXB bean describing a test class.
   */
  @XmlRootElement(name = "testsuite")
  @XmlAccessorType(XmlAccessType.FIELD)
  static class TestSuite {
    @XmlAttribute private final String name;
    @XmlTransient private final Class<?> testClass;

    @XmlAttribute private int errors;
    @XmlAttribute private int failures;
    @XmlAttribute private int skipped;
    @XmlAttribute private String hostname;
    @XmlAttribute private int tests;
    @XmlAttribute private String time;
    @XmlAttribute private String timestamp;

    @XmlElementRef
    @XmlElementWrapper(name = "properties")
    private final List<Property> properties = Lists.newArrayList(
        Iterables.transform(System.getProperties().entrySet(),
            new Function<Entry<Object, Object>, Property>() {
              @Override public Property apply(Entry<Object, Object> entry) {
                return new Property(entry.getKey().toString(), entry.getValue().toString());
              }
            }));
    @XmlElementRef private final List<TestCase> testCases = Lists.newArrayList();
    @XmlElement(name = "system-out") private String out;
    @XmlElement(name = "system-err") private String err;

    @XmlTransient private long startNs;

    // for JAXB
    private TestSuite() {
      name = null;
      testClass = null;
    }

    TestSuite(Description test) {
      name = test.getClassName();
      testClass = test.getTestClass();
      try {
        hostname = InetAddress.getLocalHost().getHostName();
      } catch (UnknownHostException e) {
        hostname = "localhost";
      }
    }

    public int getErrors() {
      return errors;
    }

    public int getFailures() {
      return failures;
    }

    public int getSkipped() {
      return skipped;
    }

    public String getHostname() {
      return hostname;
    }

    public String getName() {
      return Util.sanitizeSuiteName(name);
    }

    public int getTests() {
      return tests;
    }

    public String getTime() {
      return time;
    }

    public String getTimestamp() {
      return timestamp;
    }

    public List<Property> getProperties() {
      return properties;
    }

    public List<TestCase> getTestCases() {
      return testCases;
    }

    public String getOut() {
      return out;
    }

    public void setOut(String out) {
      this.out = out;
    }

    public String getErr() {
      return err;
    }

    public void setErr(String err) {
      this.err = err;
    }

    public void started() {
      if (startNs == 0) {
        timestamp = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss").format(new Date());
        startNs = System.nanoTime();
      }
    }

    public void finished() {
      tests++;
      if (startNs != 0) {
        time = convertTimeSpanNs(System.nanoTime() - startNs);
      } else {
        time = "0";
      }
    }

    public void incrementFailures() {
      failures++;
    }

    public void incrementErrors() {
      errors++;
    }

    public void incrementSkipped() {
      skipped++;
    }

    public boolean wasStarted() {
      return startNs > 0;
    }
  }

  private final Map<String, TestSuite> suites = Maps.newHashMap();
  private final Map<String, TestCase> cases = Maps.newHashMap();

  private final File outdir;
  private final StreamSource streamSource;

  AntJunitXmlReportListener(File outdir, StreamSource streamSource) {
    this.outdir = outdir;
    this.streamSource = streamSource;
  }

  @Override
  public void testRunStarted(Description description) throws java.lang.Exception {
    createSuites(description.getChildren());
  }

  private TestSuite getTestSuiteFor(Description description) {
    return suites.get(description.getClassName());
  }

  private TestCase getTestCaseFor(Description description) {
    return cases.get(Util.getPantsFriendlyDisplayName(description));
  }

  private void createSuites(Iterable<Description> tests) throws java.lang.Exception {
    for (Description test : tests) {
      createSuites(test.getChildren());
      if (test.isTest()) {
        String testClass = test.getClassName();
        TestSuite suite = suites.get(testClass);
        if (suite == null) {
          suite = new TestSuite(test);
          suites.put(testClass, suite);
        }
        TestCase testCase = new TestCase(test);
        suite.testCases.add(testCase);
        cases.put(Util.getPantsFriendlyDisplayName(test), testCase);
      }
    }
  }

  @Override
  public void testStarted(Description description) throws java.lang.Exception {
    if (!Util.isRunnable(description)) return;
    getTestSuiteFor(description).started();
    getTestCaseFor(description).started();
  }

  @Override
  public void testAssumptionFailure(Failure failure) {
    Description description = failure.getDescription();
    if (!description.isTest()) {
      return;
    }

    TestSuite suite = getTestSuiteFor(description);
    if (suite != null) {
      suite.incrementSkipped();
    }

    TestCase testCase = getTestCaseFor(description);
    if (testCase != null) {
      testCase.setSkipped(true);
    }
  }

  @Override
  public void testFailure(Failure failure) throws java.lang.Exception {
    Description description = failure.getDescription();
    boolean isFailure = Util.isAssertionFailure(failure);

    TestSuite suite = getTestSuiteFor(description);
    if (suite == null) {
      incrementUnknownSuiteFailure(description);
    } else {
      if (isFailure) {
        suite.incrementFailures();
      } else {
        suite.incrementErrors();
      }
    }

    Exception exception = new Exception(failure);
    TestCase testCase = getTestCaseFor(description);
    if (testCase == null) {
      testCase = incrementUnknownTestCaseFailure(description, exception);
      if (description.isSuite()) {
        // If we get a testFailure callback for a test suite then there is usually a
        // problem with initialization and we won't get a testFinished callback so
        // call finish here.
        testCase.finished();
        suite.testCases.clear();
        suite.testCases.add(testCase);
        suite.finished();
      }
    } else {
      if (isFailure) {
        testCase.setFailure(exception);
      } else {
        testCase.setError(exception);
      }
    }
  }

  @Override
  public void testIgnored(Description description) throws java.lang.Exception {
    if (!description.isTest()) {
      return;
    }

    TestSuite suite = getTestSuiteFor(description);
    if (suite != null) {
      suite.incrementSkipped();
      // Ignored tests don't have testStarted and testFinished callbacks so call finish here.
      suite.finished();
    }

    TestCase testCase = getTestCaseFor(description);
    if (testCase != null) {
      testCase.setSkipped(true);
    }
  }

  @Override
  public void testFinished(Description description) throws java.lang.Exception {
    if (!Util.isRunnable(description)) {
      return;
    }

    TestCase testCase = getTestCaseFor(description);
    if (testCase != null) {
      testCase.finished();
    } else {
      throw new RuntimeException("No TestCase for '" + description.getClassName() + "#"
          + description.getMethodName() + "'");
    }

    TestSuite suite = getTestSuiteFor(description);
    if (suite != null) {
      suite.finished();
    } else {
      throw new RuntimeException("No suite for '" + description.getClassName() + "'.");
    }
  }

  @Override
  public void testRunFinished(Result result) throws java.lang.Exception {
    for (TestSuite suite : suites.values()) {
      if (suite.wasStarted() && suite.testClass != null) {
        suite.setOut(new String(streamSource.readOut(suite.testClass), Charsets.UTF_8));
        suite.setErr(new String(streamSource.readErr(suite.testClass), Charsets.UTF_8));
      }

      if (suite.tests > 0) {
        Writer xmlOut = new FileWriter(
            new File(outdir, String.format("TEST-%s.xml", suite.getName())));

        // Only output valid XML1.0 characters - JAXB does not handle this.
        JAXB.marshal(suite, new XmlWriter(xmlOut) {
          @Override protected void handleInvalid(int c) throws IOException {
            out.write(' ');
          }
        });
      }
    }
  }

  private abstract static class XmlWriter extends FilterWriter {
    protected XmlWriter(Writer out) {
      super(out);
    }

    @Override
    public void write(char[] cbuf, int off, int len) throws IOException {
      for (int i = off; i < len; i++) {
        write(cbuf[i]);
      }
    }

    @Override
    public void write(String str, int off, int len) throws IOException {
      for (int i = off; i < len; i++) {
        write(str.charAt(i));
      }
    }

    @Override
    public void write(int c) throws IOException {
      // Only output valid XML1.0 characters by default.
      // See the spec here: http://www.w3.org/TR/2000/REC-xml-20001006#NT-Char

      // This is a complex boolean expression but it follows the spec referenced above exactly and
      // so it seems to provide clarity.
      // SUPPRESS CHECKSTYLE RegexpSinglelineJava
      if (c == 0x9
          || c == 0xA
          || c == 0xD
          || ((0x20 <= c) && (c <= 0xD7FF))
          || ((0xE000 <= c) && (c <= 0xFFFD))
          || ((0x10000 <= c) && (c <= 0x10FFFF))) {

        out.write(c);
      } else {
        handleInvalid(c);
      }
    }

    /**
     * Subclasses can handle invalid XML 1.0 characters as appropriate.
     *
     * @param c The invalid character.
     * @throws IOException If there is a problem using this stream while handling the invalid
     *     character.
     */
    protected abstract void handleInvalid(int c) throws IOException;
  }

  /**
   * Placeholder for failures that we can't attribute to a particular test suite.
   */
  static class UnknownFailureSuite {
  }

  /**
   * Record as much information as we can about test failures that occur before the test
   * actually gets run.
   *
   * Situations where this happens:
   *   - testFailure() gets passed Desription.TEST_MECHANISM
   *   - Class initialization fails and the Description passed to testFailure() may only have a
   *   string description.
   *
   * @param description description passed to {@link #testFailure(Failure)}
   */
  private void incrementUnknownSuiteFailure(Description description) {
    if (description == null || description.getClassName() == null) {
      description = Description.createTestDescription(UnknownFailureSuite.class, "unknown");
    }
    TestSuite unknownSuite = getTestSuiteFor(description);
    if (unknownSuite == null) {
      unknownSuite = new TestSuite(description);
      suites.put(description.getClassName(), unknownSuite);
    }
    unknownSuite.incrementFailures();
  }

  /**
   * Record as much information as we can about test failures that occur before the test
   * actually gets run.
   *
   * Situations where this happens:
   *   - testFailure() gets passed Description.TEST_MECHANISM
   *   - Class initialization fails and the Description passed to testFailure() may only have a
   *   string description.
   *
   * @param description description passed to {@link #testFailure(Failure)}
   * @param exception exception to record.
   */
  private TestCase incrementUnknownTestCaseFailure(Description description, Exception exception) {
    TestCase unknownCase = getTestCaseFor(description);
    if (unknownCase == null) {
      unknownCase = new TestCase(description);
      cases.put(Util.getPantsFriendlyDisplayName(description), unknownCase);
    }
    unknownCase.setError(exception);
    return unknownCase;
  }

  private static String convertTimeSpanNs(long timespanNs) {
    return String.format("%f", timespanNs / (double) TimeUnit.SECONDS.toNanos(1));
  }

  @VisibleForTesting
  protected Map<String, TestSuite> getSuites() {
    return suites;
  }

  @VisibleForTesting
  protected Map<String, TestCase> getCases() {
    return cases;
  }
}
