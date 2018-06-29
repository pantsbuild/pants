package org.pantsbuild.tools.junit.impl.security;

import java.io.FileDescriptor;
import java.security.AccessController;
import java.security.Permission;
import java.security.PrivilegedActionException;
import java.security.PrivilegedExceptionAction;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.logging.Logger;

import org.pantsbuild.junit.security.SecurityViolationException;

import static org.pantsbuild.tools.junit.impl.security.JunitSecurityManagerConfig.*;

public class JunitSecViolationReportingManager extends SecurityManager {

  private static Logger logger = Logger.getLogger("pants-junit-sec-mgr");

  private final JunitSecurityContextLookupAndErrorCollection contextLookupAndErrorCollection;

  private static final Set<String> localhostNames = new HashSet<>();

  static {
    localhostNames.add("localhost");
    localhostNames.add("127.0.0.1");
  }

  public JunitSecViolationReportingManager(JunitSecurityManagerConfig config) {
    super();
    this.contextLookupAndErrorCollection = new JunitSecurityContextLookupAndErrorCollection(config);
  }

  public static <T> T maybeWithSecurityManagerContext(
      final String className,
      final Callable<T> callable) throws Exception {
    SecurityManager securityManager = System.getSecurityManager();
    // skip if there is no security manager, or it's not the one we expect.
    if (!(securityManager instanceof JunitSecViolationReportingManager)) {
      return callable.call();
    }
    final JunitSecViolationReportingManager jsecViolationReportingManager;
    jsecViolationReportingManager = (JunitSecViolationReportingManager) securityManager;
    try {
      // doPrivileged here allows us to wrap all
      return AccessController.doPrivileged(
          new PrivilegedExceptionAction<T>() {
            @Override
            public T run() throws Exception {
              try {
                return jsecViolationReportingManager.withSettings(
                    new ContextKey(className),
                    callable);
              } catch (Exception e) {
                throw e;
              } catch (Throwable t) {
                throw new RuntimeException(t);
              }
            }
          },
          AccessController.getContext()
      );
    } catch (PrivilegedActionException e) {
      throw e.getException();
    }
  }

  public boolean disallowsThreadsFor(TestSecurityContext context) {
    return contextLookupAndErrorCollection.disallowsThreadsFor(context);
  }

  public boolean perClassThreadHandling() {
    return contextLookupAndErrorCollection.config.getThreadHandling() ==
        ThreadHandling.disallowLeakingTestSuiteThreads;
  }

  void startTest(String className, String methodName) {
    contextLookupAndErrorCollection.startTest(
        TestSecurityContext.newTestCaseContext(
            className,
            methodName,
            contextFor(className)));
  }

  void endTest() {
    contextLookupAndErrorCollection.endTest();
  }

  void startSuite(String className) {
    contextLookupAndErrorCollection.startSuite(new ContextKey(className));
  }

  public boolean anyHasDanglingThreads() {
    return contextLookupAndErrorCollection.anyHasRunningThreads();
  }

  public boolean finished() {
    return contextLookupAndErrorCollection.endRun();
  }

  public <V> V withSettings(ContextKey context, Callable<V> callable) throws Throwable {
    if (context.isSuiteKey()) {
      log("withSettings", "start suite");

      startSuite(context.getClassName());
    } else {
      contextLookupAndErrorCollection.startTest(context);
    }
    try {
      return callable.call();
    } catch (RuntimeException e) {
      throw e.getCause();
    } finally {
      contextLookupAndErrorCollection.endTest();
    }
  }

  TestSecurityContext contextFor(String className) {
    return contextLookupAndErrorCollection.getContextForClassName(className);
  }

  TestSecurityContext contextFor(String className, String methodName) {
    return contextLookupAndErrorCollection.getContext(new ContextKey(className, methodName));
  }

  public void interruptDanglingThreads() {
  }

  public boolean disallowSystemExit() {
    return contextLookupAndErrorCollection.disallowSystemExit();
  }

  private TestSecurityContext lookupContext() {
    TestSecurityContext cheaperContext =
        contextLookupAndErrorCollection.lookupWithoutExaminingClassContext();

    if (cheaperContext != null) {
      return cheaperContext;
    }

    Class[] classContext = getClassContext();
    return contextLookupAndErrorCollection.lookupContextFromClassContext(classContext);
  }

  @Override
  public Object getSecurityContext() {
    return contextLookupAndErrorCollection.getCurrentSecurityContext();
  }

  @Override
  public void checkPermission(Permission perm) {
    if (deferPermission(perm)) {
      super.checkPermission(perm);
    }
    // TODO disallow setSecurityManager if we are in a test context
  }

  @Override
  public void checkPermission(Permission perm, Object context) {
    super.checkPermission(perm, context);
  }

  private boolean deferPermission(Permission perm) {
    return false;
  }

  @Override
  public ThreadGroup getThreadGroup() {
    TestSecurityContext testSecurityContext = lookupContext();
    if (testSecurityContext != null) {
      return testSecurityContext.getThreadGroup();
    } else {
      return null;
    }
  }

  @Override
  public void checkExit(int status) {
    if (disallowSystemExit()) {
      // TODO improve message so that it points out the line the call happened on more explicitly.
      //
      SecurityException ex;
      TestSecurityContext context = lookupContext();
      if (context != null) {
        ex = new SecurityViolationException("System.exit calls are not allowed.");
        context.addFailure(ex);
      } else {
        log("checkExit", "Couldn't find a context for disallowed system exit!");
        ex = new SecurityViolationException("System.exit calls are not allowed.");
      }
      throw ex;
    }
    // docs say to call super before throwing.
    super.checkExit(status);
  }

  @Override
  public void checkConnect(final String host, final int port) {
    doCheckConnect(host, port);
  }

  @Override
  public void checkConnect(final String host, final int port, Object context1) {
    doCheckConnect(host, port);
  }

  private void doCheckConnect(String host, int port) {
    if (disallowConnectionTo(host, port)) {
      SecurityException ex;
      TestSecurityContext context = lookupContext();
      String message = networkCallDisallowedMessage(host, port);
      if (context != null) {
        ex = new SecurityViolationException(message);
        context.addFailure(ex);
      } else {
        log(
            "checkConnect",
            "Couldn't find a context for disallowed connection to '" + host + "'!");
        ex = new SecurityViolationException(message);
      }
      throw ex;
    }
    super.checkConnect(host, port);
  }

  private String networkCallDisallowedMessage(String host, int port) {
    if (port == -1) {
      return "DNS request for " + host + " is not allowed.";
    }
    return "Network call to " + host + ":" + port + " is not allowed.";
  }

  private boolean disallowConnectionTo(String host, int port) {
    switch (contextLookupAndErrorCollection.config.getNetworkHandling()) {
      case allowAll:
        return false;
      case onlyLocalhost:
        return !hostIsLocalHost(host);
    }

    return contextLookupAndErrorCollection.config.getNetworkHandling() != NetworkHandling.allowAll;
  }

  private boolean hostIsLocalHost(String host) {
    return localhostNames.contains(host);
  }

  @Override
  public void checkRead(FileDescriptor fd) {

  }

  @Override
  public void checkRead(String filename, Object context) {

  }

  @Override
  public void checkRead(String filename) {

  }

  @Override
  public void checkWrite(FileDescriptor fd) {

  }

  @Override
  public void checkWrite(String filename) {

  }

  private static void log(String methodName, String msg) {
    logger.fine("---" + methodName + ":" + msg);
  }

}
