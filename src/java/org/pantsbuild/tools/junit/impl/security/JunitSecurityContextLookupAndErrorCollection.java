package org.pantsbuild.tools.junit.impl.security;

import java.util.Collection;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Manages the lifecycles of tests and suites used by the security manager to figure out what
 * context code that might call into it is calling from.
 */
class JunitSecurityContextLookupAndErrorCollection {

  // lifecycle
  // execution contexts:
  //   StaticContext
  //      when the class containing tests is loaded
  //   SuiteContext
  //      while the beforeclass et al are being run -- analogous to classBlock in the block runner
  //      But, classes may not always be 1:1 with suites
  //   TestContext
  //      while the test case is running
  //
  // thread contexts:

  //    Test class context / might also be suite context
  //       holds threads started in the class/suite context
  //    Test case context
  //       holds threads started in the method/case context
  //    Q should threads started in a static context be considered to exist in the class context?
  //
  // Flag possibilities
  // exception handling:
  //   allow tests to swallow Security exceptions
  //   force test failure on Sec exceptions
  // scopes:
  //   test suite
  //   all tests
  //   test case
  //   static eval
  //
  // file:
  //   disallow all
  //   allow only specified files / dirs
  //   allow all
  //
  // network:
  //   disallow all
  //   allow only localhost and loop back
  //   allow only localhost connections, but allow dns resolve to see if address is pointed at
  //              localhost
  //   allow all
  //
  // scheme.
  //   sets a thread local with the testSecurityContext
  //   if a thread is created, injects the testSecurityContext into its thread local table when it
  //   is constructed.
  //   not sure if thats possible.
  //   could use this for ThreadGroups

  // Permissions to write checks for.
  // java.io.FilePermission
  // , java.net.SocketPermission,
  // java.net.NetPermission,
  // java.security.SecurityPermission,
  // java.lang.RuntimePermission,
  // java.util.PropertyPermission, java.awt.AWTPermission, java.lang.reflect.ReflectPermission,
  // and java.io.SerializablePermission.

  // TODO handling of writing Contexts for suites and failures is pretty messy and may have problems
  // across threads if notifiers are not synchronized. Notifiers are synchronized, though

  private final ThreadLocal<TestSecurityContext> settingsRef = new ThreadLocal<>();
  private final Map<String, TestSecurityContext> classNameToSuiteContext = new HashMap<>();
  private static final Logger logger = Logger.getLogger("junit-security-context");
  static {
    logger.setLevel(Level.FINEST);
  }
  final JunitSecurityManagerConfig config;
  private AtomicBoolean runEnded = new AtomicBoolean(false);

  JunitSecurityContextLookupAndErrorCollection(JunitSecurityManagerConfig config) {
    this.config = config;
  }

  private void removeCurrentThreadSecurityContext() {
    settingsRef.remove();
  }

  void startTest(TestSecurityContext testSecurityContext) {
    TestSecurityContext suiteContext =
        classNameToSuiteContext.get(testSecurityContext.getClassName());
    if (suiteContext != null) {
      suiteContext.addChild(testSecurityContext);
    } else {
      TestSecurityContext value =
          TestSecurityContext.newSuiteContext(testSecurityContext.getClassName());
      classNameToSuiteContext.put(testSecurityContext.getClassName(), value);
      value.addChild(testSecurityContext);
    }
    getAndSetLocal(testSecurityContext);
  }

  void startTest(ContextKey contextKey) {
    log("starting test " + contextKey);
    TestSecurityContext suiteContext = classNameToSuiteContext.get(contextKey.getClassName());
    if (suiteContext == null) {
      log("  no suite, creating one.");
      suiteContext = TestSecurityContext.newSuiteContext(contextKey.getClassName());
      classNameToSuiteContext.put(contextKey.getClassName(), suiteContext);
    } else {
      log("  found suite");
    }

    TestSecurityContext testSecurityContext =
        TestSecurityContext.newTestCaseContext(contextKey, suiteContext);
    suiteContext.addChild(testSecurityContext);
    getAndSetLocal(testSecurityContext);
  }

  void startSuite(ContextKey contextKey) {
    log("starting suite " + contextKey);
    TestSecurityContext securityContext =
        TestSecurityContext.newSuiteContext(contextKey.getClassName());
    getAndSetLocal(securityContext);
    classNameToSuiteContext.put(contextKey.getClassName(), securityContext);
  }

  private void getAndSetLocal(TestSecurityContext testSecurityContext) {
    TestSecurityContext andSet = settingsRef.get();
    settingsRef.set(testSecurityContext);
    if (andSet != null) {
      // complain maybe.
    }
  }

  private Collection<String> availableClasses() {
    return classNameToSuiteContext.keySet();
  }

  void endTest() {
    removeCurrentThreadSecurityContext();
  }

  TestSecurityContext getCurrentSecurityContext() {
    return settingsRef.get();
  }

  TestSecurityContext getContextForClassName(String className) {
    return classNameToSuiteContext.get(className);
  }

  boolean anyHasRunningThreads() {
    for (Map.Entry<String, TestSecurityContext> k : classNameToSuiteContext.entrySet()) {
      if (k.getValue().hasActiveThreads()) {
        return true;
      }
    }
    return false;
  }

  TestSecurityContext getContext(ContextKey contextKey) {
    if (contextKey.getClassName() != null) {
      TestSecurityContext suiteContext =
          classNameToSuiteContext.get(contextKey.getClassName());
      if (suiteContext == null) {
        return null;
      }
      if (contextKey.isSuiteKey()) {
        return suiteContext;
      }
      if (suiteContext.hasNoChildren()) {
        return suiteContext;
      }
      return suiteContext.getChild(contextKey.getMethodName());
    }
    return null;
  }

  TestSecurityContext lookupContextByThreadGroup() {
    ContextKey contextKey =
        ContextKey.parseFromThreadGroupName(Thread.currentThread().getThreadGroup().getName());
    return getContext(contextKey);
  }

  boolean disallowsThreadsFor(TestSecurityContext context) {
    switch (config.getThreadHandling()) {
      case allowAll:
        return false;
      case disallow:
        return true;
      case disallowLeakingTestCaseThreads:
        return true;
      case disallowLeakingTestSuiteThreads:
        return context.isSuite();
      default:
        return false;
    }
  }

  TestSecurityContext lookupWithoutExaminingClassContext() {
    TestSecurityContext cheaperContext = null;
    TestSecurityContext contextFromRef = getCurrentSecurityContext();
    if (contextFromRef != null) {
      logFine("lookupContext: found via ref!");
      cheaperContext = contextFromRef;
    }

    if (cheaperContext == null) {
      TestSecurityContext contextFromThreadGroup = lookupContextByThreadGroup();
      if (contextFromThreadGroup != null) {
        logFine("lookupContext: found via thread group");
        cheaperContext = contextFromThreadGroup;
      } else {
        logger.fine("lookupContext: not found thread group: " +
                        Thread.currentThread().getThreadGroup().getName());
        logFine("lookupContext: available " + availableClasses());
      }
    }
    return cheaperContext;
  }

  private void logFine(String s) {
    logger.fine(s);
  }

  private void log(String s) {
    logger.fine(s);
  }


  TestSecurityContext lookupContextFromClassContext(Class[] classContext) {
    for (Class<?> c : classContext) {
      // Will only find the classes context and not the test cases, but it's better than not finding
      // any
      TestSecurityContext testSecurityContext = getContextForClassName(c.getName());
      if (testSecurityContext != null) {
        logFine("lookupContext: found matching stack element!");
        return testSecurityContext;
      }
    }
    return null;
  }

  public boolean disallowSystemExit() {
    if (runEnded.get()) {
      return false;
    } else {
      return config.disallowSystemExit();
    }
  }

  public boolean endRun() {
    return runEnded.getAndSet(true);
  }
}
