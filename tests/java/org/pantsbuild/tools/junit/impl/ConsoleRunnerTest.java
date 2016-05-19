// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.PrintStream;
import org.apache.commons.io.FileUtils;
import org.hamcrest.CoreMatchers;
import org.junit.Assert;
import org.junit.Test;
import org.pantsbuild.tools.junit.lib.AnnotatedSerialTest1;
import org.pantsbuild.tools.junit.lib.FlakyTest;
import org.pantsbuild.tools.junit.lib.MockTest4;
import org.pantsbuild.tools.junit.lib.SerialTest1;
import org.pantsbuild.tools.junit.lib.TestRegistry;

import static org.hamcrest.CoreMatchers.not;
import static org.hamcrest.MatcherAssert.assertThat;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
/**
 * Tests features in ConsoleRunner.
 * TODO: Parameterize this test and re-run them all with the experimental runner turned on
 */
public class ConsoleRunnerTest extends ConsoleRunnerTestBase {

  /**
   * <P>This test is Parameterized to run with different combinations of
   * -default-concurrency and -use-experimental-runner flags.
   * </P>
   * <P>
   * See {@link ConsoleRunnerTestBase#invokeConsoleRunner(String)}
   * </P>
   */
  public ConsoleRunnerTest(TestParameters parameters) {
    super(parameters);
  }

  @Test
  public void testNormalTesting() {
    invokeConsoleRunner("MockTest1 MockTest2 MockTest3");
    assertEquals("test11 test12 test13 test21 test22 test31 test32",
        TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting02() {
    invokeConsoleRunner("MockTest1 MockTest2 MockTest3 -test-shard 0/2");
    assertEquals("test11 test13 test22 test32", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting13() {
    invokeConsoleRunner("MockTest1 MockTest2 MockTest3 -test-shard 1/3");
    assertEquals("test12 test22", TestRegistry.getCalledTests());
  }
  @Test
  public void testShardedTesting23() {
    invokeConsoleRunner("MockTest1 MockTest2 MockTest3 -test-shard 2/3");
    // This tests a corner case when no tests from MockTest2 are going to run.
    assertEquals("test13 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting12WithParallelThreads() {
    invokeConsoleRunner("MockTest1 MockTest2 MockTest3 "
        + "-test-shard 1/2 -parallel-threads 4 -default-concurrency PARALLEL_CLASSES");
    assertEquals("test12 test21 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting23WithParallelThreads() {
    // This tests a corner case when no tests from MockTest2 are going to run.
    invokeConsoleRunner("MockTest1 MockTest2 MockTest3 "
        + "-test-shard 2/3 -parallel-threads 3 -default-concurrency PARALLEL_CLASSES");
    assertEquals("test13 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testFlakyTests() {
    FlakyTest.reset();

    try {
      invokeConsoleRunner("FlakyTest -num-retries 2 -default-concurrency SERIAL");
      fail("Should have failed with RuntimeException due to FlakyTest.methodAlwaysFails");
      // FlakyTest.methodAlwaysFails fails this way - though perhaps that should be fixed to be an
      // RTE subclass.
    } catch (RuntimeException ex) {
      // Expected due to FlakyTest.methodAlwaysFails()
    }

    assertEquals("expected_ex flaky1 flaky1 flaky2 flaky2 flaky2 flaky3 flaky3 flaky3 "
        + "notflaky", TestRegistry.getCalledTests());

    // Verify that FlakyTest class has been instantiated once per test method invocation,
    // including flaky test method invocations.
    assertEquals(10, FlakyTest.numFlakyTestInstantiations);

    // Verify that a method with expected exception is not treated
    // as flaky - that is, it should be invoked only once.
    assertEquals(1, FlakyTest.numExpectedExceptionMethodInvocations);
  }

  @Test
  public void testTestCase() {
    invokeConsoleRunner("SimpleTestCase");
    assertEquals("testDummy", TestRegistry.getCalledTests());
  }

  @Test
  public void testConsoleOutput() {
    ByteArrayOutputStream outContent = new ByteArrayOutputStream();
    PrintStream stdout = System.out;
    PrintStream stderr = System.err;
    try {
      System.setOut(new PrintStream(outContent));
      System.setErr(new PrintStream(new ByteArrayOutputStream()));

      invokeConsoleRunner("MockTest4 -parallel-threads 1 -xmlreport");
      Assert.assertEquals("test41 test42", TestRegistry.getCalledTests());
      String output = outContent.toString();
      assertThat(output, CoreMatchers.containsString("test41"));
      assertThat(output, CoreMatchers.containsString("start test42"));
      assertThat(output, CoreMatchers.containsString("end test42"));
    } finally {
      System.setOut(stdout);
      System.setErr(stderr);
    }
  }

  @Test
  public void testOutputDir() throws Exception {
    String outdir = temporary.newFolder("testOutputDir").getAbsolutePath();
    invokeConsoleRunner("MockTest4 -parallel-threads 1 -default-concurrency PARALLEL_CLASSES"
        + " -xmlreport -outdir " + outdir);
    Assert.assertEquals("test41 test42", TestRegistry.getCalledTests());

    String testClassName = MockTest4.class.getCanonicalName();
    String output = FileUtils.readFileToString(new File(outdir, testClassName + ".out.txt"));
    assertThat(output, CoreMatchers.containsString("test41"));
    assertThat(output, CoreMatchers.containsString("start test42"));
    assertThat(output, CoreMatchers.containsString("end test42"));
  }

  @Test
  public void testParallelAnnotation() throws Exception {
    invokeConsoleRunner("AnnotatedParallelTest1 AnnotatedParallelTest2 -parallel-threads 2");
    assertEquals("aptest1 aptest2", TestRegistry.getCalledTests());
  }

  @Test
  public void testSerialAnnotation() throws Exception {
    AnnotatedSerialTest1.reset();
    invokeConsoleRunner("AnnotatedSerialTest1 AnnotatedSerialTest2 "
        + "-default-concurrency PARALLEL_CLASSES -parallel-threads 2");
    assertEquals("astest1 astest2", TestRegistry.getCalledTests());
  }

  /* LEGACY, remove after -default-parallel argument is removed */
  @Test
  public void testParallelDefaultParallel() throws Exception {
    invokeConsoleRunner("ParallelTest1 ParallelTest2 -parallel-threads 2 -default-parallel");
    assertEquals("ptest1 ptest2", TestRegistry.getCalledTests());
  }

  @Test
  public void testConcurrencyParallelClasses() throws Exception {
    invokeConsoleRunner("ParallelTest1 ParallelTest2 "
        + "-parallel-threads 2 -default-concurrency PARALLEL_CLASSES");
    assertEquals("ptest1 ptest2", TestRegistry.getCalledTests());
  }

  @Test
  public void testConcurrencyParallelBoth() throws Exception {
    invokeConsoleRunner("ParallelMethodsDefaultParallelTest1 ParallelMethodsDefaultParallelTest2"
            + " -default-concurrency PARALLEL_BOTH -parallel-threads 4");
    assertEquals("pmdptest11 pmdptest12 pmdptest21 pmdptest22", TestRegistry.getCalledTests());
  }

  @Test
  public void testConcurrencySerial() throws Exception {
    SerialTest1.reset();
    invokeConsoleRunner("SerialTest1 SerialTest2"
            + " -default-concurrency SERIAL -parallel-threads 4");
    assertEquals("stest1 stest2", TestRegistry.getCalledTests());
  }

  @Test
  public void testMockJUnit3Test() throws Exception {
    invokeConsoleRunner("MockJUnit3Test");
    assertEquals("mju3t1", TestRegistry.getCalledTests());
  }

  @Test
  public void testMockRunWithTest() throws Exception {
    invokeConsoleRunner("MockRunWithTest");
    assertEquals("mrwt1-bar mrwt1-foo", TestRegistry.getCalledTests());
  }

  @Test
  public void testNotATestNoPublicConstructor() throws Exception {
    // This class contains no public constructor. The test runner should ignore
    invokeConsoleRunner("NotATestNoPublicConstructor");
    assertEquals("", TestRegistry.getCalledTests());
  }

  @Test
  public void testNotATestPrivateClass() throws Exception {
    // This class is private. The test runner should ignore
    invokeConsoleRunner("NotATestPrivateClass$PrivateClass");
    assertEquals("", TestRegistry.getCalledTests());
  }

  @Test
  public void testNotATestNoRunnableMethods() throws Exception {
    // This class has no runnable methods. The test runner should ignore
    invokeConsoleRunner("NotATestNoRunnableMethods");
    assertEquals("", TestRegistry.getCalledTests());
  }

  @Test
  public void testNotATestNonzeroArgConstructor() throws Exception {
    // This class doesn't have a zero args public constructor, test runner should ignore
    invokeConsoleRunner("NotATestNonzeroArgConstructor");
    assertEquals("", TestRegistry.getCalledTests());
  }

  @Test
  public void testNotATestAbstractClass() throws Exception {
    // This class is abstract, test runner should ignore
    invokeConsoleRunner("NotATestAbstractClass");
    assertEquals("", TestRegistry.getCalledTests());
  }

  @Test
  public void testNotATestInterface() throws Exception {
    // This class is abstract, test runner should ignore
    invokeConsoleRunner("NotATestInterface");
    assertEquals("", TestRegistry.getCalledTests());
  }


  @Test
  public void testLegacyConcurrencyOptions() {
    // New style option overrides old
    assertEquals(Concurrency.SERIAL,
        ConsoleRunnerImpl.computeConcurrencyOption(Concurrency.SERIAL, true));
    assertEquals(Concurrency.SERIAL,
        ConsoleRunnerImpl.computeConcurrencyOption(Concurrency.SERIAL, false));
    assertEquals(Concurrency.PARALLEL_CLASSES,
        ConsoleRunnerImpl.computeConcurrencyOption(Concurrency.PARALLEL_CLASSES, false));
    assertEquals(Concurrency.PARALLEL_METHODS,
        ConsoleRunnerImpl.computeConcurrencyOption(Concurrency.PARALLEL_METHODS, false));
    assertEquals(Concurrency.PARALLEL_BOTH,
        ConsoleRunnerImpl.computeConcurrencyOption(Concurrency.PARALLEL_BOTH, false));

    assertEquals(Concurrency.SERIAL,
        ConsoleRunnerImpl.computeConcurrencyOption(null, false));
    assertEquals(Concurrency.PARALLEL_CLASSES,
        ConsoleRunnerImpl.computeConcurrencyOption(null, true));
  }
}
