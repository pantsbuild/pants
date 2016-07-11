// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.runner;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.io.Reader;
import java.net.URL;
import java.net.URLClassLoader;
import java.util.concurrent.atomic.AtomicReference;

import javax.annotation.Nullable;

import com.google.common.base.Charsets;
import com.google.common.io.CharStreams;
import com.google.common.io.Closeables;

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

  static class StreamReader extends Thread {
    static StreamReader start(InputStream stream) {
      StreamReader reader = new StreamReader(stream);
      reader.start();
      return reader;
    }

    private final Reader reader;
    @Nullable private String capturedData;

    private StreamReader(InputStream stream) {
      reader = new BufferedReader(new InputStreamReader(stream, Charsets.UTF_8));
    }

    @Override
    public void run() {
      try {
        capturedData = CharStreams.toString(reader);
      } catch (IOException e) {
        throw new RuntimeException(e);
      } finally {
        Closeables.closeQuietly(reader);
      }
    }

    @Nullable
    String readAll() throws InterruptedException {
      join();
      return capturedData;
    }
  }

  @BeforeClass
  public static void setUpClass() throws Exception {
    String command = "./pants bundle " + TEST_PROJECT;
    Process process = Runtime.getRuntime().exec(command);
    StreamReader stdout = StreamReader.start(process.getInputStream());
    StreamReader stderr = StreamReader.start(process.getErrorStream());
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
