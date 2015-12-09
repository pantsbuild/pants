// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.runner;

import java.io.*;
import java.lang.String;
import java.net.URL;
import java.net.URLClassLoader;
import java.util.concurrent.atomic.AtomicReference;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.fail;

public class PantsRunnerTest {
  /**
   * Contains:
   * <PRE>
   * META-INF/MANIFEST.MF
   * org/pantsbuild/tools/runner/testproject/MainClass.class
   * </PRE>
   */
  static final File MAIN_JAR =
      new File("tests/resources/org/pantsbuild/tools/runner/main-class.jar");

  /**
   * Contains:
   * <PRE>
   * META-INF/MANIFEST.MF
   * </PRE>
   */
  static final File SYNTHETIC_JAR =
      new File("tests/resources/org/pantsbuild/tools/runner/synthetic.jar");

  static final String MAIN_CLASS = "org.pantsbuild.tools.runner.testproject.MainClass";

  @Test
  public void testPantsRunnerWorkingWithSyntheticJarWithArg() throws Exception {
    assertOutputIsExpected("Hello! [arg1]",
        new URL[]{SYNTHETIC_JAR.toURI().toURL()}, new String[]{MAIN_CLASS, "arg1"});
  }

  @Test
  public void testPantsRunnerWorkingWithSyntheticJarWithoutArg() throws Exception {
    assertOutputIsExpected("Hello! []",
        new URL[]{SYNTHETIC_JAR.toURI().toURL()}, new String[]{MAIN_CLASS});
  }

  @Test()
  public void testPantsRunnerWorkingWithSyntheticJarWithWrongMainClass() throws Exception {
    assertExceptionWasThrown("There is no com.wow Main class",
        new URL[]{SYNTHETIC_JAR.toURI().toURL()}, new String[]{"com.wow"});
  }

  @Test
  public void testPantsRunnerWithTwoJars() throws Exception {
    assertExceptionWasThrown("Should be only one jar in classpath",
        new URL[]{SYNTHETIC_JAR.toURI().toURL(), MAIN_JAR.toURI().toURL()},
        new String[]{MAIN_CLASS});
  }

  public void testPantsRunnerWithoutSyntheticJar() throws Exception {
    assertExceptionWasThrown("jar should be synthetic with classpath attr",
        new URL[]{MAIN_JAR.toURI().toURL()},
        new String[]{MAIN_CLASS});
  }

  private static void assertExceptionWasThrown(String expectedMessage,
                                               URL[] classpath, String[] args) {
    boolean failed = true;
    try {
      runRunner(classpath, args);
      failed = false;
    } catch (Exception e) {
      assertEquals(expectedMessage, e.getMessage());
    }

    if (!failed) {
      fail();
    }
  }

  private static void assertOutputIsExpected(String expected, URL[] classpath, String[] args)
      throws Exception {
    String output = runRunner(classpath, args);
    assertEquals(expected, output);
  }

  /**
   * Hacky method to run "integration"-like tests on Runner.
   *
   * @return Output of the executed program.
   */
  private static String runRunner(URL[] classpath, final String[] args)
      throws Exception {
    ByteArrayOutputStream replacementStream = new ByteArrayOutputStream();
    PrintStream originalStream = System.out;
    System.setOut(new PrintStream(replacementStream));
    try {
      final AtomicReference<Exception> exceptionRef = new AtomicReference<Exception>();
      Thread thread = new Thread(new Runnable() {
        @Override
        public void run() {
          try {
            PantsRunner.main(args);
          } catch (Exception e) {
            exceptionRef.set(e);
          }
        }
      });
      thread.setContextClassLoader(new URLClassLoader(classpath));
      thread.start();
      thread.join();

      if (exceptionRef.get() != null) {
        throw exceptionRef.get();
      }
    } finally {
      System.setOut(originalStream);
    }

    return replacementStream.toString();
  }
}
