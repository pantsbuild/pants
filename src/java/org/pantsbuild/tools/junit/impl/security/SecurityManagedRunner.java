package org.pantsbuild.tools.junit.impl.security;

import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Queue;
import java.util.Set;
import java.util.logging.Logger;

import org.junit.runner.Description;
import org.junit.runner.Result;
import org.junit.runner.Runner;
import org.junit.runner.manipulation.Filter;
import org.junit.runner.manipulation.Filterable;
import org.junit.runner.manipulation.NoTestsRemainException;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;
import org.junit.runner.notification.RunNotifier;
import org.pantsbuild.junit.security.SecurityViolationException;

/**
 * Runs tests wrapped with the reporting security manager.
 */
public class SecurityManagedRunner extends Runner implements Filterable {
  private static Logger logger = Logger.getLogger("pants-junit");
  private final Runner wrappedRunner;
  private final JunitSecViolationReportingManager securityManager;

  public SecurityManagedRunner(
      Runner wrappedRunner,
      JunitSecViolationReportingManager securityManager) {
    this.wrappedRunner = wrappedRunner;
    this.securityManager = securityManager;
  }

  @Override public Description getDescription() {
    return wrappedRunner.getDescription();
  }

  @Override public void run(RunNotifier notifier) {
    // NB: SecListener needs to be the first listener, otherwise the failures it fires will not be
    // in the xml results or the console output. This is because those are constructed with
    // subsequent listeners.
    notifier.addFirstListener(new SecListener(notifier, securityManager));

    recurseThroughChildrenMarkingSuites();
    log("after add seclistener");
    wrappedRunner.run(notifier);
    log("After wrapped runner");
  }

  private void recurseThroughChildrenMarkingSuites() {
    // TODO: should this init the test cases too, or just the suites?
    // TODO: should suites reference their parents?
    Set<Description> seen =  new HashSet<>();
    Queue<Description> queue = new ArrayDeque<>();
    queue.add(wrappedRunner.getDescription());
    while (!queue.isEmpty()) {

      Description pop = queue.remove();
      if (seen.contains(pop)) {
        continue;
      }
      seen.add(pop);
      if (pop.isSuite()) {
        securityManager.startSuite(pop.getClassName());
      }

      for (Description description : pop.getChildren()) {
        if (!seen.contains(description)){
          queue.add(description);
        }
      }
    }
  }

  private static void log(String s) {
    logger.fine(s);
  }

  // NB: Pass filter calls through.
  // This allows filtered requests to apply to the underlying tests. In some cases, leaving this
  // unimplemented may cause tests to run multiple times.
  @Override
  public void filter(Filter filter) throws NoTestsRemainException {
    if (wrappedRunner instanceof Filterable) {
      ((Filterable) wrappedRunner).filter(filter);
    } else {
      // TODO decide what to do with this case.
      throw new RuntimeException(
          "Internal Error: runner " + wrappedRunner.getClass() + " does not support filtering");
    }
  }

  public enum TestState {
    started,
    failed,
    danglingThreads
  }

  /**
   * Manages the life cycles of the various contexts that things are run in.
   *
   * - It notifies the security manager when a test is about to run.
   * - It Injects security failures into the run results.
   *
   * The
   */
  public static class SecListener extends RunListener {
    private final RunNotifier runNotifier;
    private final Map<Description, TestState> tests =  new HashMap<>();
    private final JunitSecViolationReportingManager securityManager;

    SecListener(RunNotifier runNotifier, JunitSecViolationReportingManager securityManager) {
      this.runNotifier = runNotifier;
      this.securityManager = securityManager;
    }

    @Override
    public void testRunStarted(Description description) throws Exception {
      // might want to have a nested settings here in the manager
      log("run started");
    }

    // testRunFinished is for all of the tests.
    // TODO This currently is run for each runner. It might make sense to extract a runner that just
    //      includes this and only runs it once.
    @Override
    public void testRunFinished(Result result) throws Exception {
      // Mark the run as finished, and if it was previously marked, skip checks.
      if (securityManager.finished()) {
        return;
      }
      for (Description description : tests.keySet()) {
        if (tests.get(description) == TestState.failed) {
          // NB if it's already failed, just show the initial
          // failure.
          continue;
        }
        TestSecurityContext context = contextFor(description);
        if (description.isTest()) {
          if (context.hadFailures()) {
            handleSecurityFailure(description, context);
          }
          handleDanglingThreads(description, context);
        } else if (description.isSuite()) {
          if (context.hadFailures()) {
            handleSecurityFailure(description, context);
          }
          handleDanglingThreads(description, context);
        } else {
          throwNotSuiteOrTest(description);
        }
      }

      Set<Class<?>> classNames = new HashSet<>();
      for (Description description : tests.keySet()) {
        classNames.add(description.getTestClass());
      }
      for (Class<?> className : classNames) {
        TestSecurityContext context = securityManager.contextFor(className.getCanonicalName());
        if (context != null) {
          if (context.hadFailures()) {
            handleSecurityFailure(Description.createSuiteDescription(className), context);
          }
          if (securityManager.perClassThreadHandling()) {
            handleDanglingThreads(Description.createSuiteDescription(className), context);
          }
        }
      }

    }

    @Override
    public void testStarted(Description description) throws Exception {
      log("test-started: " + description);
      if (description.isTest()) {

        String methodName = description.getMethodName();
        securityManager.startTest(description.getClassName(), methodName);

      } else if (description.isSuite()){
        // TODO if we never get here, then we shouldn't bother
        securityManager.startSuite(description.getClassName());
      } else {
        throwNotSuiteOrTest(description);
      }
      tests.put(description, TestState.started);
    }

    @Override
    public void testFailure(Failure failure) throws Exception {
      tests.put(failure.getDescription(), TestState.failed);
    }

    @Override
    public void testAssumptionFailure(Failure failure) {
      tests.put(failure.getDescription(), TestState.failed);
    }

    @Override
    public void testFinished(Description description) throws Exception {
      TestState testState = tests.get(description);
      if (testState == TestState.failed) {
        // NB if it's already failed, just show the initial
        // failure.
        return;
      }

      TestSecurityContext context = contextFor(description);
      if (description.isTest()) {
        try {
          if (context.hadFailures()) {
            handleSecurityFailure(description, context);
          }
          handleDanglingThreads(description, context);
        } finally {
          securityManager.endTest();
        }
      } else if (description.isSuite()) {
        if (context.hadFailures()) {
          handleSecurityFailure(description, context);
        }
        handleDanglingThreads(description, context);
      }
    }

    void handleSecurityFailure(Description description, TestSecurityContext context) {
      if (tests.get(description) == TestState.failed) {
        return;
      }
      Throwable cause = context.firstFailure();
      fireFailure(description, cause);
      tests.put(description, TestState.failed);
    }

    void handleDanglingThreads(Description description, TestSecurityContext context) {
      if (context.hasActiveThreads()) {
        if (securityManager.disallowsThreadsFor(context)) {
          fireFailure(description, new SecurityViolationException(
              "Threads from " + description + " are still running (" +
                  context.getThreadGroup().activeCount() + "):\n"
                  + getThreadGroupListing(context.getThreadGroup())));
          tests.put(description, TestState.failed);
        } else {
          tests.put(description, TestState.danglingThreads);
        }
      }
    }

    private String getThreadGroupListing(ThreadGroup threadGroup) {
      Thread[] threads = new Thread[threadGroup.activeCount()];
      threadGroup.enumerate(threads);
      StringBuilder sb = new StringBuilder();
      for (Thread thread : threads) {
        if (thread == null)
          break;
        sb.append("\t\t" + thread .getName()+ "\n");
      }
      return sb.toString();
    }

    TestSecurityContext contextFor(Description description) {
      return securityManager.contextFor(description.getClassName(), description.getMethodName());
    }

    private void throwNotSuiteOrTest(Description description) {
      // Used as the last case in if stanzas checking isSuite/isTest
      throw new RuntimeException(
          "Expected " + description.getDisplayName() +
              " to be a suite or test, but was neither");
    }

    private void fireFailure(Description description, Throwable cause) {
      runNotifier.fireTestFailure(new Failure(description, cause));
    }

    private void log(String x) {
      logger.fine("-SecListener-  " + x);
    }
  }
}
