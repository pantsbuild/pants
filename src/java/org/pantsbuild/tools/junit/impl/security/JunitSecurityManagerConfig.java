package org.pantsbuild.tools.junit.impl.security;

public class JunitSecurityManagerConfig {

  private final SystemExitHandling systemExitHandling;
  private final ThreadHandling threadHandling;
  private final NetworkHandling networkHandling;

  public JunitSecurityManagerConfig(
      SystemExitHandling systemExitHandling,
      ThreadHandling threadHandling,
      NetworkHandling networkHandling) {
    this.systemExitHandling = systemExitHandling;
    this.threadHandling = threadHandling;
    this.networkHandling = networkHandling;
  }

  boolean disallowSystemExit() {
    return systemExitHandling == SystemExitHandling.disallow;
  }

  public ThreadHandling getThreadHandling() {
    return threadHandling;
  }

  public NetworkHandling getNetworkHandling() {
    return networkHandling;
  }

  public enum SystemExitHandling {
    /**
     * Allow tests to call System.exit. Not sure why you'd want that, but ...
     */
    allow,
    /**
     * Disallow tests from calling System.exit
     */
    disallow
  }

  public enum ThreadHandling {
    /**
     * Allow threads, and allow them to live indefinitely.
     */
    allowAll,
    /**
     * Do not allow threads to be started via tests.
     */
    disallow,
    /**
     * disallow suites starting threads, but allow test cases to start them as long as they are
     * killed before the end of the test case.
     */
    disallowLeakingTestCaseThreads,
    /**
     * Allow suites or test cases to start threads,
     * but ensure they are killed at the end of the suite.
     */
    disallowLeakingTestSuiteThreads,

    // Other possible options:
    //
    //nestedButLeakingDisallowed
    // Needs a better name, could be same as dangling suite mode.
    // threads started in a context, case or suite can live as long as the context does, but it's an
    // error if they live past it.
    //
    // a set of variants that warns instead of disallowing
  }

  public enum NetworkHandling {
    /**
     * Allow all network requests
     */
    allowAll,
    /**
     * Disallow all network requests
     */
    disallow,
    /**
     * Allow network requests to localhost and deny all others.
     */
    onlyLocalhost
  }
}
