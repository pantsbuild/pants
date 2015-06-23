package org.pantsbuild.tools.junit.impl;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.PrintStream;
import org.apache.commons.io.FileUtils;
import org.junit.Assert;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class ConsoleRunnerConsoleOutputTest extends ConsoleRunnerTestHelper {

  @Rule
  public TemporaryFolder temporary = new TemporaryFolder();

  @Test
  public void testConsoleOutput() throws Exception {
    ByteArrayOutputStream outContent = new ByteArrayOutputStream();
    PrintStream stdout = System.out;
    PrintStream stderr = System.err;
    System.setOut(new PrintStream(outContent));
    System.setErr(new PrintStream(new ByteArrayOutputStream()));
    ConsoleRunnerImpl.main(asArgsArray("MockTest4 -parallel-threads 1 -xmlreport"));
    System.setOut(stdout);
    System.setErr(stderr);
    Assert.assertEquals("test41 test42", TestRegistry.getCalledTests());
    assertContainsTestOutput(outContent.toString());
  }

  @Test
  public void testOutputDir() throws Exception {
    String outdir = temporary.newFolder("testOutputDir").getAbsolutePath();
    ConsoleRunnerImpl.main(asArgsArray(
        "MockTest4 -parallel-threads 1 " +
        "-default-parallel -suppress-output -xmlreport -outdir " + outdir));
    Assert.assertEquals("test41 test42", TestRegistry.getCalledTests());
    String prefix = MockTest4.class.getCanonicalName();
    String fileOutputLines = FileUtils.readFileToString(new File(outdir, prefix + ".out.txt"));
    assertContainsTestOutput(fileOutputLines);
  }
}
