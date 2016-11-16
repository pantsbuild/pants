// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import com.google.common.base.Charsets;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.PrintStream;
import org.apache.commons.io.FileUtils;
import org.junit.Assert;
import org.junit.Test;
import org.pantsbuild.tools.junit.lib.AnnotatedParallelClassesAndMethodsTest1;
import org.pantsbuild.tools.junit.lib.AnnotatedParallelMethodsTest1;
import org.pantsbuild.tools.junit.lib.AnnotatedParallelTest1;
import org.pantsbuild.tools.junit.lib.AnnotatedSerialTest1;
import org.pantsbuild.tools.junit.lib.ConsoleRunnerTestBase;
import org.pantsbuild.tools.junit.lib.FlakyTest;
import org.pantsbuild.tools.junit.lib.MockBurstParallelClassesAndMethodsTest1;
import org.pantsbuild.tools.junit.lib.MockBurstParallelMethodsTest;
import org.pantsbuild.tools.junit.lib.MockParameterizedParallelClassesAndMethodsTest1;
import org.pantsbuild.tools.junit.lib.MockParameterizedParallelMethodsTest;
import org.pantsbuild.tools.junit.lib.MockTest4;
import org.pantsbuild.tools.junit.lib.ParallelClassesAndMethodsDefaultParallelTest1;
import org.pantsbuild.tools.junit.lib.ParallelMethodsDefaultParallelTest1;
import org.pantsbuild.tools.junit.lib.ParallelTest1;
import org.pantsbuild.tools.junit.lib.SerialTest1;
import org.pantsbuild.tools.junit.lib.TestRegistry;

import static org.hamcrest.CoreMatchers.anyOf;
import static org.hamcrest.CoreMatchers.containsString;
import static org.hamcrest.MatcherAssert.assertThat;
import static org.hamcrest.core.Is.is;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.fail;
import static org.junit.Assume.assumeThat;

/**
/**
 * Tests features in ConsoleRunner.
 * <P>
 * See also {@link XmlReportTest}
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
  public void testShardedTesting12() {
    invokeConsoleRunner("MockTest1 MockTest2 MockTest3 "
        + "-test-shard 1/2");
    assertEquals("test12 test21 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting03() {
    invokeConsoleRunner("MockTest1 MockTest2 MockTest3 -test-shard 0/3");
    assertEquals("test11 test21 test32", TestRegistry.getCalledTests());
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
  public void testShardedTesting04() {
    invokeConsoleRunner("MockTest1 MockTest2 MockTest3 -test-shard 0/4");
    assertEquals("test11 test22", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting14() {
    invokeConsoleRunner("MockTest1 MockTest2 MockTest3 -test-shard 1/4");
    assertEquals("test12 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting24() {
    invokeConsoleRunner("MockTest1 MockTest2 MockTest3 -test-shard 2/4");
    assertEquals("test13 test32", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting34() {
    invokeConsoleRunner("MockTest1 MockTest2 MockTest3 -test-shard 3/4");
    assertEquals("test21", TestRegistry.getCalledTests());
  }

  @Test
  public void testFlakyTests() {
    assumeThat(parameters.defaultConcurrency, is(Concurrency.SERIAL));
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
      assertThat(output, containsString("test41"));
      assertThat(output, containsString("start test42"));
      assertThat(output, containsString("end test42"));
    } finally {
      System.setOut(stdout);
      System.setErr(stderr);
    }
  }

  @Test
  public void testOutputDir() throws Exception {
    assumeThat(parameters.defaultConcurrency, is(Concurrency.PARALLEL_CLASSES));

    String outdir = temporary.newFolder("testOutputDir").getAbsolutePath();
    invokeConsoleRunner("MockTest4 -parallel-threads 1 -default-concurrency PARALLEL_CLASSES "
        + "-xmlreport -outdir " + outdir);
    Assert.assertEquals("test41 test42", TestRegistry.getCalledTests());

    String testClassName = MockTest4.class.getCanonicalName();
    String output = FileUtils.readFileToString(
        new File(outdir, testClassName + ".out.txt"), Charsets.UTF_8);
    assertThat(output, containsString("test41"));
    assertThat(output, containsString("start test42"));
    assertThat(output, containsString("end test42"));
  }

  @Test
  public void testParallelAnnotation() throws Exception {
    AnnotatedParallelTest1.reset();
    invokeConsoleRunner("AnnotatedParallelTest1 AnnotatedParallelTest2 -parallel-threads 2");
    assertEquals("aptest1 aptest2", TestRegistry.getCalledTests());
  }

  @Test
  public void testParallelMethodsAnnotation() throws Exception {
    // @ParallelTestMethods only works reliably under the experimental runner
    assumeThat(parameters.useExperimentalRunner, is(true));
    AnnotatedParallelMethodsTest1.reset();
    invokeConsoleRunner("AnnotatedParallelMethodsTest1 AnnotatedParallelMethodsTest2"
        + " -parallel-threads 2");
    assertEquals("apmtest11 apmtest12 apmtest21 apmtest22", TestRegistry.getCalledTests());
  }

  @Test
  public void testParallelClassesAndMethodsAnnotation() throws Exception {
    // @ParallelClassesAndMethods only works reliably under the experimental runner
    assumeThat(parameters.useExperimentalRunner, is(true));
    AnnotatedParallelClassesAndMethodsTest1.reset();
    invokeConsoleRunner("AnnotatedParallelClassesAndMethodsTest1"
        + " AnnotatedParallelClassesAndMethodsTest2 -parallel-threads 4");
    assertEquals("apcamtest11 apcamtest12 apcamtest21 apcamtest22", TestRegistry.getCalledTests());
  }

  @Test
  public void testSerialAnnotation() throws Exception {
    AnnotatedSerialTest1.reset();
    invokeConsoleRunner("AnnotatedSerialTest1 AnnotatedSerialTest2");
    assertEquals("astest1 astest2", TestRegistry.getCalledTests());
  }

  /* LEGACY, remove after -default-parallel argument is removed */
  @Test
  public void testParallelDefaultParallel() throws Exception {
    ParallelTest1.reset();
    invokeConsoleRunner("ParallelTest1 ParallelTest2 -default-parallel -parallel-threads 2");
    assertEquals("ptest1 ptest2", TestRegistry.getCalledTests());
  }

  @Test
  public void testConcurrencyParallelClasses() throws Exception {
    assumeThat(parameters.defaultConcurrency, is(Concurrency.PARALLEL_CLASSES));
    ParallelTest1.reset();
    invokeConsoleRunner("ParallelTest1 ParallelTest2 -parallel-threads 2"
        + " -default-concurrency PARALLEL_CLASSES");
    assertEquals("ptest1 ptest2", TestRegistry.getCalledTests());
  }

  @Test
  public void testConcurrencyParallelMethods() throws Exception {
    // -default-concurrency PARALLEL_METHODS tests only work reliably with the experimental runner
    assumeThat(parameters.useExperimentalRunner, is(true));
    assumeThat(parameters.defaultConcurrency, is(Concurrency.PARALLEL_METHODS));
    ParallelMethodsDefaultParallelTest1.reset();
    invokeConsoleRunner("ParallelMethodsDefaultParallelTest1 ParallelMethodsDefaultParallelTest2"
        + " -default-concurrency PARALLEL_METHODS -parallel-threads 4");
    assertEquals("pmdptest11 pmdptest12 pmdptest21 pmdptest22", TestRegistry.getCalledTests());
  }

  @Test
  public void testConcurrencyParallelClassesAndMethods() throws Exception {
    assumeThat(parameters.defaultConcurrency, is(Concurrency.PARALLEL_CLASSES_AND_METHODS));
    ParallelClassesAndMethodsDefaultParallelTest1.reset();
    invokeConsoleRunner("ParallelClassesAndMethodsDefaultParallelTest1"
        + " ParallelClassesAndMethodsDefaultParallelTest2"
        + " -default-concurrency PARALLEL_CLASSES_AND_METHODS -parallel-threads 4");
    assertEquals("pbdptest11 pbdptest12 pbdptest21 pbdptest22", TestRegistry.getCalledTests());
  }

  @Test
  public void testConcurrencySerial() throws Exception {
    // This test only works when concurrency is serial
    assumeThat(parameters.defaultConcurrency, is(Concurrency.SERIAL));
    SerialTest1.reset();
    invokeConsoleRunner("SerialTest1 SerialTest2");
    assertEquals("stest1 stest2", TestRegistry.getCalledTests());
  }


  @Test
  public void testBurst() {
    invokeConsoleRunner("MockBurstTest");
    assertEquals("btest1:BOTTOM btest1:CHARM btest1:DOWN btest1:STRANGE btest1:TOP btest1:UP",
        TestRegistry.getCalledTests());
  }

  @Test
  public void testConcurrencyParameterizedParallelMethods() {
    // -default-concurrency PARALLEL_METHODS tests only work reliably with the experimental runner
    assumeThat(parameters.useExperimentalRunner, is(true));
    // Requires parallel methods
    assumeThat(parameters.defaultConcurrency, is(Concurrency.PARALLEL_METHODS));
    MockParameterizedParallelMethodsTest.reset();
    invokeConsoleRunner("MockParameterizedParallelMethodsTest -parallel-threads 3");
    assertEquals("ppmtest1:one ppmtest1:three ppmtest1:two", TestRegistry.getCalledTests());
  }

  @Test
  public void testConcurrencyParameterizedParallelClassesAndMethods() {
    // -default-concurrency PARALLEL_CLASSES_AND_METHODS tests only work reliably with the
    // experimental runner
    assumeThat(parameters.useExperimentalRunner, is(true));
    // Requires parallel methods
    assumeThat(parameters.defaultConcurrency, is(Concurrency.PARALLEL_CLASSES_AND_METHODS));
    MockParameterizedParallelClassesAndMethodsTest1.reset();
    invokeConsoleRunner("MockParameterizedParallelClassesAndMethodsTest1"
        + " MockParameterizedParallelClassesAndMethodsTest2 -parallel-threads 5");
    assertEquals("ppcamtest1:param1 ppcamtest1:param2 ppcamtest1:param3"
            + " ppcamtest2:arg1 ppcamtest2:arg2",
        TestRegistry.getCalledTests());
  }

  @Test
  public void testConcurrencyBurstParallelMethods() {
    // -default-concurrency PARALLEL_METHODS tests only work reliably with the experimental runner
    assumeThat(parameters.useExperimentalRunner, is(true));
    // Requires parallel methods
    assumeThat(parameters.defaultConcurrency, anyOf(is(Concurrency.PARALLEL_METHODS),
        is(Concurrency.PARALLEL_CLASSES_AND_METHODS)));
    MockBurstParallelMethodsTest.reset();
    invokeConsoleRunner("MockBurstParallelMethodsTest -parallel-threads 6");
    assertEquals("bpmtest1:BOTTOM bpmtest1:CHARM bpmtest1:DOWN bpmtest1:STRANGE "
        + "bpmtest1:TOP bpmtest1:UP",
        TestRegistry.getCalledTests());
  }

  @Test
  public void testConcurrencyBurstParallelClassesAndMethods() {
    // -default-concurrency PARALLEL_CLASSES_AND_METHODS tests only work reliably with the
    // experimental runner
    assumeThat(parameters.useExperimentalRunner, is(true));
    // Requires parallel methods
    assumeThat(parameters.defaultConcurrency, is(Concurrency.PARALLEL_CLASSES_AND_METHODS));
    MockBurstParallelClassesAndMethodsTest1.reset();
    invokeConsoleRunner("MockBurstParallelClassesAndMethodsTest1"
        + " MockBurstParallelClassesAndMethodsTest2 -parallel-threads 5");
    assertEquals("bpcamtest1:BLUE bpcamtest1:RED"
        + " bpcamtest2:APPLE bpcamtest2:BANANA bpcamtest2:CHERRY",
        TestRegistry.getCalledTests());
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
  public void testMockScalaTest() throws Exception {
    invokeConsoleRunner("MockScalaTest");
    assertEquals("MockScalaTest-1", TestRegistry.getCalledTests());
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
  public void testNotATestScalaClass() throws Exception {
    // This class is a basic scala class, test runner should ignore
    invokeConsoleRunner("NotAScalaTest");
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
    assertEquals(Concurrency.PARALLEL_CLASSES_AND_METHODS,
        ConsoleRunnerImpl.computeConcurrencyOption(Concurrency.PARALLEL_CLASSES_AND_METHODS,
            false));

    assertEquals(Concurrency.SERIAL,
        ConsoleRunnerImpl.computeConcurrencyOption(null, false));
    assertEquals(Concurrency.PARALLEL_CLASSES,
        ConsoleRunnerImpl.computeConcurrencyOption(null, true));
  }
}
