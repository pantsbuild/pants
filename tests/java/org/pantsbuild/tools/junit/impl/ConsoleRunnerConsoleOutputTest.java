package org.pantsbuild.tools.junit.impl;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.PrintStream;
import org.apache.commons.io.FileUtils;
import org.junit.AfterClass;
import org.junit.Assert;
import org.junit.BeforeClass;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class ConsoleRunnerConsoleOutputTest extends ConsoleRunnerTestHelper {

  @Rule
  public TemporaryFolder temporary = new TemporaryFolder();

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

  @Test
  public void testConsoleOutput() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray("MockTest4 -parallel-threads 1 -xmlreport"));
    Assert.assertEquals("test41 test42", TestRegistry.getCalledTests());
    assertContainsTestOutput(outContent.toString());
  }

  @Test
  public void testOutputDir() throws Exception {
    String outdir = temporary.newFolder("testOutputDir").getAbsolutePath();
    ConsoleRunnerImpl.main(asArgsArray(
        "MockTest4 -parallel-threads 1 " +
            "-default-parallel -xmlreport -suppress-output -outdir " + outdir));
    Assert.assertEquals("test41 test42",
        TestRegistry.getCalledTests());

    String prefix = MockTest4.class.getCanonicalName();
    String fileOutputLines = FileUtils.readFileToString(new File(outdir, prefix + ".out.txt"));
    assertContainsTestOutput(fileOutputLines);
  }
}
