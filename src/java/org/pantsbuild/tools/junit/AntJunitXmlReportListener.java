// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit;

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
import javax.xml.bind.annotation.XmlAttribute;
import javax.xml.bind.annotation.XmlElement;
import javax.xml.bind.annotation.XmlElementRef;
import javax.xml.bind.annotation.XmlElementWrapper;
import javax.xml.bind.annotation.XmlRootElement;
import javax.xml.bind.annotation.XmlValue;

import com.google.common.base.Charsets;
import com.google.common.base.Function;
import com.google.common.collect.ImmutableList;
import com.google.common.collect.Iterables;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;

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
  static class Exception {
    private final String message;
    private final String type;
    private final String stacktrace;

    Exception() {
      // for JAXB
      message = null;
      type = null;
      stacktrace = null;
    }

    Exception(Failure failure) {
      message = failure.getMessage();
      type = failure.getException().getClass().getName();
      stacktrace = failure.getTrace();
    }

    @XmlAttribute
    public String getMessage() {
      return message;
    }

    @XmlAttribute
    public String getType() {
      return type;
    }

    @XmlValue
    public String getStacktrace() {
      return stacktrace;
    }
  }

  /**
   * A JAXB bean describing an individual test method.
   */
  @XmlRootElement(name = "testcase")
  static class TestCase {
    private final String classname;
    private final String name;
    private String time;
    private Exception failure;
    private Exception error;
    private long startNs;

    TestCase() {
      // for JAXB
      classname = null;
      name = null;
    }

    TestCase(Description test) {
      classname = test.getClassName();
      name = test.getMethodName();
    }

    @XmlAttribute
    public String getClassname() {
      return classname;
    }

    @XmlAttribute
    public String getName() {
      return name;
    }

    @XmlAttribute
    public String getTime() {
      return time;
    }

    @XmlElement
    public Exception getFailure() {
      return failure;
    }

    public void setFailure(Exception failure) {
      this.failure = failure;
    }

    @XmlElement
    public Exception getError() {
      return error;
    }

    public void setError(Exception error) {
      this.error = error;
    }

    public void started() {
      startNs = System.nanoTime();
    }

    public void finished() {
      time = convertTimeSpanNs(System.nanoTime() - startNs);
    }
  }

  /**
   * A JAXB bean describing an individual system property.
   */
  @XmlRootElement(name = "property")
  static class Property {
    private final String name;
    private final String value;

    Property() {
      // for JAXB
      name = null;
      value = null;
    }

    Property(String name, String value) {
      this.name = name;
      this.value = value;
    }

    @XmlAttribute
    public String getName() {
      return name;
    }

    @XmlAttribute
    public String getValue() {
      return value;
    }
  }

  /**
   * A JAXB bean describing a test class.
   */
  @XmlRootElement(name = "testsuite")
  static class TestSuite {
    private final String name;

    private int errors;
    private int failures;
    private String hostname;
    private int tests;
    private String time;
    private String timestamp;
    private final List<Property> properties = ImmutableList.copyOf(
        Iterables.transform(System.getProperties().entrySet(),
            new Function<Entry<Object, Object>, Property>() {
              @Override public Property apply(Entry<Object, Object> entry) {
                return new Property(entry.getKey().toString(), entry.getValue().toString());
              }
            }));
    private final List<TestCase> testCases = Lists.newArrayList();
    private String out;
    private String err;

    private long startNs;

    TestSuite() {
      // for JAXB
      name = null;
    }

    TestSuite(Description test) {
      name = test.getClassName();
      try {
        hostname = InetAddress.getLocalHost().getHostName();
      } catch (UnknownHostException e) {
        hostname = "localhost";
      }
    }

    @XmlAttribute
    public int getErrors() {
      return errors;
    }

    @XmlAttribute
    public int getFailures() {
      return failures;
    }

    @XmlAttribute
    public String getHostname() {
      return hostname;
    }

    @XmlAttribute
    public String getName() {
      return name;
    }

    @XmlAttribute
    public int getTests() {
      return tests;
    }

    @XmlAttribute
    public String getTime() {
      return time;
    }

    @XmlAttribute
    public String getTimestamp() {
      return timestamp;
    }

    @XmlElementRef
    @XmlElementWrapper(name = "properties")
    public List<Property> getProperties() {
      return properties;
    }

    @XmlElementRef
    public List<TestCase> getTestCases() {
      return testCases;
    }

    @XmlElement(name = "system-out")
    public String getOut() {
      return out;
    }

    public void setOut(String out) {
      this.out = out;
    }

    @XmlElement(name = "system-err")
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
      if (++tests == testCases.size()) {
        time = convertTimeSpanNs(System.nanoTime() - startNs);
      }
    }

    public void incrementFailures() {
      failures++;
    }

    public void incrementErrors() {
      errors++;
    }

    public boolean wasStarted() {
      return startNs > 0;
    }
  }

  private final Map<Class<?>, TestSuite> suites = Maps.newHashMap();
  private final Map<Description, TestCase> cases = Maps.newHashMap();

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

  private void createSuites(Iterable<Description> tests) {
    for (Description test : tests) {
      createSuites(test.getChildren());
      if (Util.isRunnable(test)) {
        Class<?> testClass = test.getTestClass();
        TestSuite suite = suites.get(testClass);
        if (suite == null) {
          suite = new TestSuite(test);
          suites.put(testClass, suite);
        }
        TestCase testCase = new TestCase(test);
        suite.testCases.add(testCase);
        cases.put(test, testCase);
      }
    }
  }

  @Override
  public void testStarted(Description description) throws java.lang.Exception {
    suites.get(description.getTestClass()).started();
    cases.get(description).started();
  }

  @Override
  public void testFailure(Failure failure) throws java.lang.Exception {
    Exception exception = new Exception(failure);

    Description description = failure.getDescription();
    TestSuite suite = suites.get(description.getTestClass());
    TestCase testCase = cases.get(description);
    if (Util.isAssertionFailure(failure)) {
      testCase.setFailure(exception);
      suite.incrementFailures();
    } else {
      testCase.setError(exception);
      suite.incrementErrors();
    }
  }

  @Override
  public void testFinished(Description description) throws java.lang.Exception {
    cases.get(description).finished();
    suites.get(description.getTestClass()).finished();
  }

  @Override
  public void testRunFinished(Result result) throws java.lang.Exception {
    for (Entry<Class<?>, TestSuite> entry : suites.entrySet()) {
      Class<?> testClass = entry.getKey();
      TestSuite suite = entry.getValue();

      if (suite.wasStarted()) {
        suite.setOut(new String(streamSource.readOut(testClass), Charsets.UTF_8));
        suite.setErr(new String(streamSource.readErr(testClass), Charsets.UTF_8));

        Writer xmlOut = new FileWriter(new File(outdir, String.format("TEST-%s.xml", suite.name)));

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

  private static String convertTimeSpanNs(long timespanNs) {
    return String.format("%f", timespanNs / (double) TimeUnit.SECONDS.toNanos(1));
  }
}
