// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.PrintStream;
import org.apache.commons.io.FileUtils;
import org.junit.After;
import org.junit.Assert;
import org.junit.Before;
import org.junit.Test;


/**
 * Tests several recently added features in ConsoleRunner.
 * TODO: cover the rest of ConsoleRunner functionality.
 */
public class ConsoleRunnerTest {

  private final ByteArrayOutputStream outContent = new ByteArrayOutputStream();
  private final ByteArrayOutputStream errContent = new ByteArrayOutputStream();

  private final PrintStream stdout = System.out;
  private final PrintStream stderr = System.err;

  @Before
  public void setUp() {
    ConsoleRunner.setCallSystemExitOnFinish(false);
    ConsoleRunner.setExitStatus(0);
    TestRegistry.reset();
  }

  @After
  public void tearDown() {
    ConsoleRunner.setCallSystemExitOnFinish(true);
    ConsoleRunner.setExitStatus(0);
  }

  @Test
  public void testNormalTesting() throws Exception {
    ConsoleRunner.main(asArgsArray("MockTest1 MockTest2 MockTest3"));
    Assert.assertEquals("test11 test12 test13 test21 test22 test31 test32",
       TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting02() throws Exception {
    ConsoleRunner.main(asArgsArray("MockTest1 MockTest2 MockTest3 -test-shard 0/2"));
    Assert.assertEquals("test11 test13 test22 test32", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting13() throws Exception {
    ConsoleRunner.main(asArgsArray("MockTest1 MockTest2 MockTest3 -test-shard 1/3"));
    Assert.assertEquals("test12 test22", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting23() throws Exception {
    // This tests a corner case when no tests from MockTest2 are going to run.
    ConsoleRunner.main(asArgsArray(
        "MockTest1 MockTest2 MockTest3 -test-shard 2/3"));
    Assert.assertEquals("test13 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting12WithParallelThreads() throws Exception {
    ConsoleRunner.main(asArgsArray(
        "MockTest1 MockTest2 MockTest3 -test-shard 1/2 -parallel-threads 4 -default-parallel"));
    Assert.assertEquals("test12 test21 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting23WithParallelThreads() throws Exception {
    // This tests a corner case when no tests from MockTest2 are going to run.
    ConsoleRunner.main(asArgsArray(
        "MockTest1 MockTest2 MockTest3 -test-shard 2/3 -parallel-threads 3 -default-parallel"));
    Assert.assertEquals("test13 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testFlakyTests() throws Exception {
    TestRegistry.consoleRunnerTestRunsFlakyTests = true;
    FlakyTest.numFlakyTestInstantiations = 0;
    FlakyTest.numExpectedExceptionMethodInvocations = 0;

    try {
      ConsoleRunner.main(asArgsArray("FlakyTest -num-retries 2"));
      Assert.fail("Should have failed with RuntimeException due to FlakyTest.methodAlwaysFails");
      // FlakyTest.methodAlwaysFails fails this way - though perhaps that should be fixed to be an
      // RTE subclass.
      // SUPPRESS CHECKSTYLE RegexpSinglelineJava
    } catch (RuntimeException ex) {
      // Expected due to FlakyTest.methodAlwaysFails()
    } finally {
      TestRegistry.consoleRunnerTestRunsFlakyTests = false;
    }

    Assert.assertEquals("expected_ex flaky1 flaky1 flaky2 flaky2 flaky2 flaky3 flaky3 flaky3 "
        + "notflaky", TestRegistry.getCalledTests());

    // Verify that FlakyTest class has been instantiated once per test method invocation,
    // including flaky test method invocations.
    Assert.assertEquals(10, FlakyTest.numFlakyTestInstantiations);

    // Verify that a method with expected exception is not treated
    // as flaky - that is, it should be invoked only once.
    Assert.assertEquals(1, FlakyTest.numExpectedExceptionMethodInvocations);
  }

  @Test
  public void testOutputDir() throws Exception {
    String outdir = new File(System.getProperty("java.io.tmpdir")).getAbsolutePath();
    ConsoleRunner.main(asArgsArray(
            "MockTest4 MockTest2 MockTest3 -parallel-threads 1 " +
                    "-default-parallel -xmlreport -outdir -suppress-output" + outdir));
    Assert.assertEquals("test21 test22 test31 test32 test41 test42", TestRegistry.getCalledTests());

    String prefix = MockTest4.class.getCanonicalName();
    String fileOutputLines = FileUtils.readFileToString(new File(outdir, prefix + ".out.txt"));
    assertContainsTestOutput(fileOutputLines);
  }

  private void assertContainsTestOutput(String output) {
    Assert.assertTrue("String: " + output, output.contains("test41"));
    Assert.assertTrue("String: " + output,  output.contains("start test42"));
    Assert.assertTrue("String: " + output, output.contains("end test42"));
  }

  private String[] asArgsArray(String cmdLine) {
    String[] args = cmdLine.split(" ");
    for (int i = 0; i < args.length; i++) {
      if (args[i].contains("Test")) {
        args[i] = getClass().getPackage().getName() + '.' + args[i];
      }
    }
    return args;
  }
}
