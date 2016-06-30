// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.runner;

import java.io.*;
import java.lang.String;
import java.net.URL;
import java.net.URLClassLoader;
import java.util.concurrent.atomic.AtomicReference;

import org.junit.BeforeClass;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

public class PantsRunnerTest {
  static final String TEST_PROJECT =
      "testprojects/src/java/org/pantsbuild/testproject/runner:pants-runner-testproject";
  static final File SYNTHETIC_JAR =
      new File("dist/testprojects.src.java.org.pantsbuild.testproject.runner.pants-runner-" +
               "testproject-bundle/pants-runner-testproject.jar");
  static final File MAIN_JAR =
      new File("dist/testprojects.src.java.org.pantsbuild.testproject.runner.pants-runner-" +
               "testproject-bundle/libs/" +
          "testprojects.src.java.org.pantsbuild.testproject.runner.main-class-0.jar");
  static final String MAIN_CLASS = "org.pantsbuild.testproject.runner.MainClass";

  static class Reader extends Thread {
    static Reader start(InputStream stream) {
      Reader reader = new Reader(stream);
      reader.start();
      return reader;
    }

    private static final int BUFFER_SIZE = 8 * 1024;

    private final InputStream stream;
    private final ByteArrayOutputStream capturedData = new ByteArrayOutputStream(BUFFER_SIZE);

    private Reader(InputStream stream) {
      this.stream = stream;
    }

    @Override
    public void run() {
      byte[] buffer = new byte[BUFFER_SIZE];
      int read;
      while ((read = read(buffer)) != -1) {
        capturedData.write(buffer, 0, read);
      }
    }

    private int read(byte[] buffer) {
      try {
        return stream.read(buffer);
      } catch (IOException e) {
        throw new RuntimeException(e);
      }
    }

    String readAll() throws InterruptedException {
      join();
      return capturedData.toString();
    }
  }

  @BeforeClass
  public static void setUpClass() throws Exception {
    String command = "./pants bundle " + TEST_PROJECT;
    Process process = Runtime.getRuntime().exec(command);
    Reader stdout = Reader.start(process.getInputStream());
    Reader stderr = Reader.start(process.getErrorStream());
    int result = process.waitFor();
    assertEquals(
        String.format(
            "Problem running %s - exited with %d:\nSTDOUT:\n%s\n\nSTDERR:\n%s",
            command,
            result,
            stdout.readAll(),
            stderr.readAll()),
        0,
        result);
    assertTrue(SYNTHETIC_JAR.exists());
    assertTrue(MAIN_JAR.exists());
  }

  @Test
  public void testSyntheticJarWithArg() throws Exception {
    assertOutputIsExpected("Hello!\n" +
            "Args: [arg1]\n" +
            "URL: pants-runner-testproject.jar\n" +
            "URL: testprojects.src.java.org." +
                 "pantsbuild.testproject.runner.main-class-0.jar\n" +
            "URL: testprojects.src.java.org." +
                 "pantsbuild.testproject.runner.dependent-class-0.jar\n",
        new URL[]{SYNTHETIC_JAR.toURI().toURL()}, new String[]{MAIN_CLASS, "arg1"});
  }

  @Test
  public void testSyntheticJarWithoutArg() throws Exception {
    assertOutputIsExpected("Hello!\n" +
            "Args: []\n" +
            "URL: pants-runner-testproject.jar\n" +
            "URL: testprojects.src.java.org." +
                 "pantsbuild.testproject.runner.main-class-0.jar\n" +
            "URL: testprojects.src.java.org." +
                 "pantsbuild.testproject.runner.dependent-class-0.jar\n",
        new URL[]{SYNTHETIC_JAR.toURI().toURL()}, new String[]{MAIN_CLASS});
  }

  @Test()
  public void testSyntheticJarWithWrongMainClass() throws Exception {
    assertExceptionWasThrown(
        ClassNotFoundException.class, "com.wow",
        new URL[]{SYNTHETIC_JAR.toURI().toURL()}, new String[]{"com.wow"});
  }

  @Test()
  public void testSyntheticJarWithNonStaticMainClass() throws Exception {
    assertExceptionWasThrown(
        IllegalArgumentException.class,
        "Method 'main' for org.pantsbuild.testproject.runner.DependentClass is not static.",
        new URL[]{SYNTHETIC_JAR.toURI().toURL()},
        new String[]{"org.pantsbuild.testproject.runner.DependentClass"});
  }

  @Test
  public void testTwoJars() throws Exception {
    assertExceptionWasThrown(
        IllegalArgumentException.class, "Should be exactly one jar file in the classpath.",
        new URL[]{SYNTHETIC_JAR.toURI().toURL(), MAIN_JAR.toURI().toURL()},
        new String[]{MAIN_CLASS});
  }

  @Test
  public void testRunWithoutSyntheticJar() throws Exception {
    assertExceptionWasThrown(
        IllegalArgumentException.class,
        "Supplied jar file doesn't contains manifest file.",
        new URL[]{MAIN_JAR.toURI().toURL()},
        new String[]{MAIN_CLASS});
  }

  private static void assertExceptionWasThrown(Class<? extends Exception> exceptionClass,
                                               String exceptionMessage,
                                               URL[] classpath, String[] args) {
    boolean failed = true;
    try {
      runRunner(classpath, args);
      failed = false;
    } catch (Exception e) {
      assertEquals(exceptionClass, e.getClass());
      assertEquals(exceptionMessage, e.getMessage());
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
