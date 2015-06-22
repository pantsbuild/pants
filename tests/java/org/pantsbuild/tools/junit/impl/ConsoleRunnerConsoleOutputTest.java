package org.pantsbuild.tools.junit.impl;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import org.junit.AfterClass;
import org.junit.Assert;
import org.junit.BeforeClass;
import org.junit.Ignore;
import org.junit.Test;

public class ConsoleRunnerConsoleOutputTest extends ConsoleRunnerTestHelper {
  final static ByteArrayOutputStream outContent = new ByteArrayOutputStream();
  final static ByteArrayOutputStream errContent = new ByteArrayOutputStream();

  final static PrintStream stdout = System.out;
  final static PrintStream stderr = System.err;

  @BeforeClass
  public static void setUpBeforeClass() throws Exception {
    System.setOut(new PrintStream(outContent));
    System.setErr(new PrintStream(errContent));
  }

  @AfterClass
  public static void tearDownAfterClass() throws Exception {
    System.setOut(stdout);
    System.setErr(stderr);
  }

  @Ignore("Re-enable this test wil junit 0.0.7 published.")
  @Test
  public void testConsoleOutput() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray("MockTest4 -parallel-threads 1 -xmlreport"));
    Assert.assertEquals("test41 test42", TestRegistry.getCalledTests());
    assertContainsTestOutput(outContent.toString());
  }
}
