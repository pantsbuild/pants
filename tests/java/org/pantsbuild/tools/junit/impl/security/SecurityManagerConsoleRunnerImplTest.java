package org.pantsbuild.tools.junit.impl.security;

import org.junit.Test;
import org.pantsbuild.tools.junit.lib.SystemExitsInObjectBody;
import org.pantsbuild.tools.junit.lib.security.fileaccess.FileAccessTests;
import org.pantsbuild.tools.junit.lib.security.network.BoundaryNetworkTests;
import org.pantsbuild.tools.junit.lib.security.sysexit.BeforeClassSysExitTestCase;
import org.pantsbuild.tools.junit.lib.security.sysexit.BoundarySystemExitTests;
import org.pantsbuild.tools.junit.impl.ConsoleRunnerImplTestSetup;
import org.pantsbuild.tools.junit.lib.security.sysexit.StaticSysExitTestCase;
import org.pantsbuild.tools.junit.lib.security.threads.DanglingThreadFromTestCase;
import org.pantsbuild.tools.junit.lib.security.threads.ThreadStartedInBeforeClassAndJoinedAfterTest;
import org.pantsbuild.tools.junit.lib.security.threads.ThreadStartedInBeforeClassAndNotJoinedAfterTest;
import org.pantsbuild.tools.junit.lib.security.threads.ThreadStartedInBeforeTest;
import org.pantsbuild.tools.junit.lib.security.threads.ThreadStartedInBodyAndJoinedAfterTest;

import static org.hamcrest.CoreMatchers.containsString;
import static org.hamcrest.MatcherAssert.assertThat;
import static org.hamcrest.core.Is.is;

public class SecurityManagerConsoleRunnerImplTest extends ConsoleRunnerImplTestSetup {

  @Test
  public void testFailSystemExit() {
    Class<BoundarySystemExitTests> testClass = BoundarySystemExitTests.class;
    String output = runTestsExpectingFailure(
        configDisallowingSystemExitButAllowingEverythingElse(),
        testClass);
    String testClassName = testClass.getCanonicalName();

    assertThat(output, containsString(") directSystemExit(" + testClassName + ")"));
    assertThat(output, containsString(") catchesSystemExit(" + testClassName + ")"));
    assertThat(output, containsString(") exitInJoinedThread(" + testClassName + ")"));
    assertThat(output, containsString(") exitInNotJoinedThread(" + testClassName + ")"));

    assertThat(output, containsString("There were 4 failures:"));
    assertThat(output, containsString("Tests run: 5,  Failures: 4"));

    assertThat(
        output,
        containsString(
            ") directSystemExit(" + testClassName + ")\n" +
                "org.pantsbuild.junit.security.SecurityViolationException: " +
                "System.exit calls are not allowed.\n"));
    assertThat(
        output,
        containsString(
            "\tat java.lang.Runtime.exit(Runtime.java:107)\n" +
                "\tat java.lang.System.exit(System.java:971)\n" +
                "\tat " + testClassName + ".directSystemExit(" + testClass.getSimpleName() +
                ".java:43)"));
  }

  @Test
  public void testWhenDanglingThreadsAllowedPassOnThreadStartedInTestCase() {
    JunitSecurityManagerConfig secMgrConfig =
        configDisallowingSystemExitButAllowingEverythingElse();
    String output = runTestsExpectingSuccess(secMgrConfig, DanglingThreadFromTestCase.class);
    assertThat(output, containsString("OK (1 test)"));
  }

  @Test
  public void testDisallowDanglingThreadStartedInTestCase() {
    Class<?> testClass = DanglingThreadFromTestCase.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.disallowLeakingTestCaseThreads,
            JunitSecurityManagerConfig.NetworkHandling.allowAll),
        testClass);
    String testClassName = testClass.getCanonicalName();
    assertThat(output, containsString("startedThread(" + testClassName + ")"));
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("Tests run: 1,  Failures: 1"));

    assertThat(output, containsString(") startedThread(" + testClassName + ")\n" +
        "org.pantsbuild.junit.security.SecurityViolationException: " +
        "Threads from startedThread(" + testClassName + ") are still running (1):\n" +
        "\t\tThread-"
    ));
  }

  @Test
  public void testThreadStartedInBeforeTestAndJoinedAfter() {
    // Expect that of the two tests, only the test that fails due to an assertion failure will fail.
    // And that it fails due to that failure
    Class<?> testClass = ThreadStartedInBeforeTest.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.disallowLeakingTestCaseThreads,
            JunitSecurityManagerConfig.NetworkHandling.allowAll),
        testClass);
    assertThat(output, containsString("failing(" + testClass.getCanonicalName() + ")"));
    assertThat(output, containsString("java.lang.AssertionError: failing"));
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("Tests run: 2,  Failures: 1"));
  }

  @Test
  public void testThreadStartedInBeforeTestAndJoinedAfterWhenSuiteLeakingDisallowed() {
    // Expect that of the two tests, only the test that fails due to an assertion failure will fail.
    // And that it fails due to that failure
    Class<?> testClass = ThreadStartedInBeforeTest.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.disallowLeakingTestSuiteThreads,
            JunitSecurityManagerConfig.NetworkHandling.allowAll),
        testClass);
    assertThat(output, containsString("failing(" + testClass.getCanonicalName() + ")"));
    assertThat(output, containsString("java.lang.AssertionError: failing"));
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("Tests run: 2,  Failures: 1"));
  }

  @Test
  public void testThreadStartedInBeforeClassAndJoinedAfterClassWithPerSuiteThreadLife() {
    // Expect that of the two tests, only the test that fails due to an assertion failure will fail.
    // And that it fails due to that failure.
    // The other failure will be ascribed to the test class instead.
    Class<?> testClass = ThreadStartedInBeforeClassAndJoinedAfterTest.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.disallowLeakingTestSuiteThreads,
            JunitSecurityManagerConfig.NetworkHandling.allowAll),
        testClass);
    assertThat(output, containsString("failing(" + testClass.getCanonicalName() + ")"));
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("Tests run: 2,  Failures: 1"));
  }

  @Test
  public void testThreadStartedInBodyAndJoinedAfterClassWithPerSuiteThreadLife() {
    // Expect that of the two tests, only the test that fails due to an assertion failure will fail.
    // And that it fails due to that failure.
    // The other failure will be ascribed to the test class instead.
    Class<?> testClass = ThreadStartedInBodyAndJoinedAfterTest.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.disallowLeakingTestSuiteThreads,
            JunitSecurityManagerConfig.NetworkHandling.allowAll),
        testClass);
    assertThat(output, containsString("failing(" + testClass.getCanonicalName() + ")"));
    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("Tests run: 2,  Failures: 1"));
  }

  @Test
  public void testThreadStartedInBodyAndJoinedAfterClassWithPerTestCaseThreadLife() {
    // Expect that of the two tests, only the test that fails due to an assertion failure will fail.
    // And that it fails due to that failure.
    // The other failure will be ascribed to the test class instead.
    Class<?> testClass = ThreadStartedInBodyAndJoinedAfterTest.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.disallowLeakingTestCaseThreads,
            JunitSecurityManagerConfig.NetworkHandling.allowAll),
        testClass);
    assertThat(output, containsString("failing(" + testClass.getCanonicalName() + ")"));
    assertThat(output, containsString("passing(" + testClass.getCanonicalName() + ")"));
    assertThat(output, containsString("There were 2 failures:"));
    assertThat(output, containsString("Tests run: 2,  Failures: 2"));
  }

  @Test
  public void testThreadStartedInBeforeClassAndNotJoinedAfterClassWithPerSuiteThreadLife() {
    // Expect that of the two tests, only the test that fails due to an assertion failure will fail.
    // And that it fails due to that failure.
    // The other failure will be ascribed to the test class instead.
    Class<?> testClass = ThreadStartedInBeforeClassAndNotJoinedAfterTest.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.disallowLeakingTestSuiteThreads,
            JunitSecurityManagerConfig.NetworkHandling.allowAll),
        testClass);

    assertThat(
        ThreadStartedInBeforeClassAndNotJoinedAfterTest.thread.getState(),
        is(Thread.State.WAITING));
    String testClassName = testClass.getCanonicalName();
    assertThat(output, containsString("failing(" + testClassName + ")"));

    assertThat(output, containsString("There were 2 failures:"));
    assertThat(output, containsString("Tests run: 2,  Failures: 2"));

    assertThat(output, containsString(") " + testClassName + "\n" +
        "org.pantsbuild.junit.security.SecurityViolationException: " +
        "Threads from " + testClassName + " are still running (1):\n" +
        "\t\tThread-"
    ));
    // stop thread waiting on the latch.
    ThreadStartedInBeforeClassAndNotJoinedAfterTest.latch.countDown();
  }

  @Test
  public void testSystemExitFromBodyOfScalaObject() {
    Class<?> testClass = SystemExitsInObjectBody.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.disallowLeakingTestSuiteThreads,
            JunitSecurityManagerConfig.NetworkHandling.allowAll),
        testClass);


    String testClassName = testClass.getCanonicalName();

    assertThat(output, containsString(
        ") initializationError(" + testClassName + ")\n" +
            "java.lang.ExceptionInInitializerError\n" +
            "\tat " + testClassName + ".<init>(SystemExitsInObjectBody.scala:12)"));
    // NB This caused by clause is hard to find in the stacktrace right now, it might make sense to
    // unwrap the error and display it.
    assertThat(output, containsString(
        "Caused by: " +
            "org.pantsbuild.junit.security.SecurityViolationException: " +
            "System.exit calls are not allowed.\n"));
  }

  @Test
  public void treatStaticSystemExitAsFailure() {
    // TODO it'd be better if this case resulted in a message that said none of the tests were run
    // because for classes with more tests, it will be difficult to understand
    Class<?> testClass = StaticSysExitTestCase.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.disallowLeakingTestCaseThreads,
            JunitSecurityManagerConfig.NetworkHandling.allowAll),
        testClass);

    assertThat(output, containsString("passingTest(" + testClass.getCanonicalName() + ")"));
    assertThat(output, containsString("System.exit calls are not allowed"));
    assertThat(output, containsString("There were 2 failures:"));
    assertThat(output, containsString("Tests run: 2,  Failures: 2"));
  }

  @Test
  public void treatBeforeClassSystemExitAsFailure() {
    Class<?> testClass = BeforeClassSysExitTestCase.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.disallowLeakingTestCaseThreads,
            JunitSecurityManagerConfig.NetworkHandling.allowAll),
        testClass);

    assertThat(output, containsString("1) " + testClass.getCanonicalName() + ""));
    assertThat(output, containsString("System.exit calls are not allowed"));
    assertThat(output, containsString("at " + testClass.getCanonicalName() + ".before("));

    assertThat(output, containsString("There was 1 failure:"));
    assertThat(output, containsString("Tests run: 0,  Failures: 1"));
  }

  @Test
  public void testFailNetworkAccess() {
    Class<BoundaryNetworkTests> testClass = BoundaryNetworkTests.class;
    BoundaryNetworkTests.reset();
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.allowAll,
            JunitSecurityManagerConfig.NetworkHandling.onlyLocalhost
        ),
        testClass);
    String testClassName = testClass.getCanonicalName();

    assertThat(output, containsString(") directNetworkCall(" + testClassName + ")"));
    assertThat(output, containsString(") catchesNetworkCall(" + testClassName + ")"));
    assertThat(output, containsString(") networkCallInJoinedThread(" + testClassName + ")"));
    assertThat(output, containsString(") networkCallInNotJoinedThread(" + testClassName + ")"));

    assertThat(output, containsString("There were 5 failures:"));
    assertThat(output, containsString("Tests run: 6,  Failures: 5"));

    assertThat(output, containsString(
        ") directNetworkCall(" + testClassName + ")\n" +
            "org.pantsbuild.junit.security.SecurityViolationException: " +
            "DNS request for example.com is not allowed.\n"));
    // ... some other ats
    assertThat(output, containsString(
        "\tat java.net.InetAddress.getAllByName0(InetAddress.java:1268)\n" +
            "\tat java.net.InetAddress.getAllByName(InetAddress.java:1192)\n" +
            "\tat java.net.InetAddress.getAllByName(InetAddress.java:1126)\n" +
            "\tat java.net.InetAddress.getByName(InetAddress.java:1076)\n" +
            "\tat java.net.InetSocketAddress.<init>(InetSocketAddress.java:220)\n" +
            "\tat " + testClassName + ".makeNetworkCall"));
  }

  @Test
  public void testAllowNetworkAccessForLocalhost() {
    Class<?> testClass = BoundaryNetworkTests.class;
    BoundaryNetworkTests.setHostname("localhost");
    String output = runTestsExpectingSuccess(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.allowAll,
            JunitSecurityManagerConfig.NetworkHandling.onlyLocalhost
        ),
        testClass);

    assertThat(output, containsString("OK (6 tests)\n"));
  }

  @Test
  public void whenNetworkAccessDisallowedFailNetworkTouchingTests() {
    Class<?> testClass = BoundaryNetworkTests.class;
    BoundaryNetworkTests.setHostname("localhost");
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.allowAll,
            JunitSecurityManagerConfig.NetworkHandling.disallow
        ),
        testClass);

    String testClassName = testClass.getCanonicalName();

    assertThat(output, containsString(") directNetworkCall(" + testClassName + ")"));
    assertThat(output, containsString(") catchesNetworkCall(" + testClassName + ")"));
    assertThat(output, containsString(") networkCallInJoinedThread(" + testClassName + ")"));
    assertThat(output, containsString(") networkCallInNotJoinedThread(" + testClassName + ")"));

    assertThat(output, containsString("There were 5 failures:"));
    assertThat(output, containsString("Tests run: 6,  Failures: 5"));

    assertThat(output, containsString(
        ") directNetworkCall(" + testClassName + ")\n" +
            "org.pantsbuild.junit.security.SecurityViolationException: " +
            "DNS request for localhost is not allowed.\n"));
    // ... some other ats
    assertThat(output, containsString(
        "\tat java.net.InetAddress.getAllByName0(InetAddress.java:1268)\n" +
            "\tat java.net.InetAddress.getAllByName(InetAddress.java:1192)\n" +
            "\tat java.net.InetAddress.getAllByName(InetAddress.java:1126)\n" +
            "\tat java.net.InetAddress.getByName(InetAddress.java:1076)\n" +
            "\tat java.net.InetSocketAddress.<init>(InetSocketAddress.java:220)\n" +
            "\tat " + testClassName + ".makeNetworkCall"));
  }

  @Test
  public void whenFileAccessSetToAllowAllTestsPass() {
    Class<?> testClass = FileAccessTests.class;
    String output = runTestsExpectingSuccess(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.allowAll,
            JunitSecurityManagerConfig.NetworkHandling.onlyLocalhost,
            JunitSecurityManagerConfig.FileHandling.allowAll
        ),
        testClass);

    assertThat(output, containsString("OK (5 tests)\n"));
  }

  @Test
  public void whenFileAccessDisallowedFileAccessFails() {
    Class<?> testClass = FileAccessTests.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.allowAll,
            JunitSecurityManagerConfig.NetworkHandling.onlyLocalhost,
            JunitSecurityManagerConfig.FileHandling.disallow
        ),
        testClass);

    assertThat(output, containsString("Failures: 5\n"));
    String testClassName = "org.pantsbuild.tools.junit.lib.security.fileaccess.FileAccessTests";
    String testFilePath = "tests/resources/org/pantsbuild/tools/junit/lib/";
    String exceptionName = "org.pantsbuild.junit.security.SecurityViolationException";
    assertThat(output,
        containsString(") readAFile(" + testClassName + ")\n" +
            exceptionName + ": Access to file: " + testFilePath + "a.file not allowed"));
    // ...
    assertThat(output,
        containsString("at " + testClassName + ".readAFile(FileAccessTests.java:"));

    assertThat(output,
        containsString(") writeAFile(" + testClassName + ")\n" +
            exceptionName + ": Access to file: " + testFilePath + "another.file not allowed"));
    // ...
    assertThat(output,
        containsString("at " + testClassName + ".writeAFile(FileAccessTests.java:"));

    assertThat(output,
        containsString(
            ") deleteAFile(" + testClassName + ")\n" +
                exceptionName + ": Access to file: " + testFilePath + "a.different.file" +
                " not allowed"));
    // ...
    assertThat(output,
        containsString("at " + testClassName + ".deleteAFile(FileAccessTests.java:"));

  }

  @Test
  public void whenFileAccessCWDDisallowedCWDPassesAndNonFails() {
    Class<?> testClass = FileAccessTests.class;
    String output = runTestsExpectingFailure(
        new JunitSecurityManagerConfig(
            JunitSecurityManagerConfig.SystemExitHandling.disallow,
            JunitSecurityManagerConfig.ThreadHandling.allowAll,
            JunitSecurityManagerConfig.NetworkHandling.onlyLocalhost,
            JunitSecurityManagerConfig.FileHandling.onlyCWD
        ),
        testClass);

    assertThat(output, containsString("Failures: 2\n"));
    String testClassName = "org.pantsbuild.tools.junit.lib.security.fileaccess.FileAccessTests";
    String testFilePath = "tests/resources/org/pantsbuild/tools/junit/lib/";
    String exceptionName = "org.pantsbuild.junit.security.SecurityViolationException";
    assertThat(output,
        containsString(") tempfile(" + testClassName + ")\n" +
            exceptionName + ": Access to file: "));
    // ...
    assertThat(output,
        containsString("at " + testClassName + ".tempfile(FileAccessTests.java:"));
    assertThat(output,
        containsString(") readNonexistentRootFile(" + testClassName + ")\n" +
            exceptionName + ": Access to file: "));
    // ...
    assertThat(output,
        containsString("at " + testClassName + ".readNonexistentRootFile(" +
            "FileAccessTests.java:"));

  }


  private JunitSecurityManagerConfig configDisallowingSystemExitButAllowingEverythingElse() {
    return new JunitSecurityManagerConfig(
        JunitSecurityManagerConfig.SystemExitHandling.disallow,
        JunitSecurityManagerConfig.ThreadHandling.allowAll,
        JunitSecurityManagerConfig.NetworkHandling.allowAll);
  }
}
