package org.pantsbuild.tools.junit.impl.security;

import java.util.ArrayDeque;
import java.util.Collection;
import java.util.Collections;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.Queue;
import java.util.Set;
import java.util.logging.Logger;
import java.util.stream.Collectors;

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

  @Override
  public Description getDescription() {
    return wrappedRunner.getDescription();
  }

  @Override
  public void run(RunNotifier notifier) {
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

    // NB: Use identity to check for seen, because Description equality only checks the DisplayName,
    //     which may have duplicate names.
    Set<Description> seen = Collections.newSetFromMap(new IdentityHashMap<Description, Boolean>());
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
        if (!seen.contains(description)) {
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
    failureReported,
    danglingThreadsExistButAllowed
  }

  /**
   * Manages the life cycles of the various contexts that things are run in.
   * <p>
   * - It notifies the security manager when a test is about to run.
   * - It Injects security failures into the run results.
   * <p>
   * The
   */
  public static class SecListener extends RunListener {
    private final RunNotifier runNotifier;
    private final Map<Description, TestState> tests = new HashMap<>();
    private final JunitSecViolationReportingManager securityManager;

    SecListener(RunNotifier runNotifier, JunitSecViolationReportingManager securityManager) {
      this.runNotifier = runNotifier;
      this.securityManager = securityManager;
    }

    // run on the main thread
    @Override
    public void testRunStarted(Description description) throws Exception {
      // might want to have a nested settings here in the manager
      log("run started");
      // todo move walk of tests here
    }

    // run on the main thread
    // testRunFinished is for all of the tests.
    @Override
    public void testRunFinished(Result result) throws Exception {
      log("run finished");
      // Mark the run as finished, and if it was previously marked, skip checks.
      if (securityManager.finished()) {
        return;
      }

      // TODO lambdas can't be shaded currently
      tests.keySet()
          .stream()
          .map(Description::getClassName)
          .collect(Collectors.toSet())
          .stream()
          .map(securityManager::contextFor).forEach(context -> {
        Description description = Description.createSuiteDescription(context.getClassName());
        resolveConstraintViolationsAndFailures(description, context);
      });

      tests.keySet().stream()
          .filter(d -> tests.get(d) != TestState.failureReported)
          .forEach(description -> {
            TestSecurityContext context = contextFor(description);
            if (description.isTest()) {
              resolveConstraintViolationsAndFailures(description, context);
            } else {
              throw new RuntimeException("wat " + description);
            }
          });
    }

    private void resolveConstraintViolationsAndFailures(
        Description description,
        TestSecurityContext context) {
      // if there were constraint violations and they haven't been reported yet, report them.
      if (context.hadFailures() && tests.get(description) != TestState.failureReported) {
        // TODO maybe if test already failed, wrap failure in a MultipleFailureException
        Throwable cause = context.firstFailure();
        fireFailure(description, cause);
        tests.put(description, TestState.failureReported);
      }

      log("desc: " + description + " checking dangling");
      if (tests.get(description) == TestState.failureReported) {
        return;
      }
      // if there are threads running and the current context does not allow threads to remain,
      // running, report a failure.
      Collection<Thread> activeThreads = context.getActiveThreads();
      if (!activeThreads.isEmpty()) {
        if (securityManager.disallowsThreadsFor(context)) {
          StringBuilder sb = new StringBuilder();
          for (Thread thread : activeThreads) {
            sb.append("\t\t" + thread.getName() + "\n");
          }
          String threadGroupListing = sb.toString();
          fireFailure(description, new SecurityViolationException(
              "Threads from " + description + " are still running (" +
                  activeThreads.size() + "):\n"
                  + threadGroupListing));

          tests.put(description, TestState.failureReported);
          log("desc: " + description + " failed dangling check");
        } else {
          tests.put(description, TestState.danglingThreadsExistButAllowed);
          log("desc: " + description + " has, but not failed dangling check");
        }
      } else {
        log("no active threads");
      }
    }

    // only called for tests not suites
    // called on the thread the test execs on
    @Override
    public void testStarted(Description description) throws Exception {
      log("test-started: " + description);
      String methodName = description.getMethodName();
      securityManager.startTest(description.getClassName(), methodName);
      tests.put(description, TestState.started);
    }

    @Override
    public void testFailure(Failure failure) throws Exception {
      if (failure.getException() instanceof SecurityViolationException) {
        tests.put(failure.getDescription(), TestState.failureReported);
      }
    }

    @Override
    public void testFinished(Description description) throws Exception {
      log("testFinished " + description);

      TestSecurityContext context = contextFor(description);
      try {
        TestState testState = tests.get(description);
        if (testState != TestState.failureReported) {
          resolveConstraintViolationsAndFailures(description, context);
        }

      } finally {
        securityManager.endTest();
      }
    }

    @Override
    public void testAssumptionFailure(Failure failure) {
      // NB unlikely to have been caused by a SecViolation. Ignore.
    }

    TestSecurityContext contextFor(Description description) {
      return securityManager.contextFor(description.getClassName(), description.getMethodName());
    }

    private void fireFailure(Description description, Throwable cause) {
      runNotifier.fireTestFailure(new Failure(description, cause));
    }

    private void log(String x) {
      logger.fine("-SecListener-  " + x);
    }
  }
}
