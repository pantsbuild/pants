package org.pantsbuild.tools.junit.impl.security;

import java.security.AccessController;
import java.security.Permission;
import java.security.PrivilegedActionException;
import java.security.PrivilegedExceptionAction;
import java.util.concurrent.Callable;
import java.util.logging.Logger;

import org.pantsbuild.junit.security.SecurityViolationException;

import static org.pantsbuild.tools.junit.impl.security.JunitSecurityManagerConfig.*;

public class JunitSecViolationReportingManager extends SecurityManager {

  private final JunitSecurityManagerLogic logic;

  private static Logger logger = Logger.getLogger("pants-junit-sec-mgr");

  private final JunitSecurityContextLookupAndErrorCollection contextLookupAndErrorCollection;


  public JunitSecViolationReportingManager(JunitSecurityManagerConfig config) {
    super();
    this.contextLookupAndErrorCollection = new JunitSecurityContextLookupAndErrorCollection(config);
    this.logic = new JunitSecurityManagerLogic(config, contextLookupAndErrorCollection);
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

  private TestSecurityContext lookupContext() {
    TestSecurityContext cheaperContext =
        contextLookupAndErrorCollection.lookupWithoutExaminingClassContext();

    if (cheaperContext != null) {
      return cheaperContext;
    }

    Class<?>[] classContext = getClassContext();
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
    // NB: this is called on thread init. The security manager looks to see whether the current
    // thread is running a test, and if so, it gives the thread a thread group that is assigned to
    // that test.
    TestSecurityContext testSecurityContext = lookupContext();
    if (testSecurityContext != null) {
      // TODO we could capture where the thread was started and display that if there's an error.
      // it may not be that useful if we're running in a pool though
      return testSecurityContext.getThreadGroup();
    } else {
      return null;
    }
  }

  @Override
  public void checkExit(int status) {
    if (logic.disallowSystemExit()) {
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
  public void checkConnect(final String host, final int port, Object context) {
    doCheckConnect(host, port);
  }

  private void doCheckConnect(String host, int port) {
    if (logic.disallowConnectionTo(host, port)) {
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

  @Override
  public void checkRead(String filename, Object context) {
    TestSecurityContext testSecurityContext = lookupContext();
    if (logic.disallowsFileAccess(testSecurityContext, filename)) {
      String message = disallowedFileAccessMessage(filename);
      log("checkRead", message);
      SecurityViolationException exception = new SecurityViolationException(message);

      testSecurityContext.addFailure(exception);
      super.checkRead(filename, context);
      throw exception;
    }
    super.checkRead(filename, context);
  }

  @Override
  public void checkRead(String filename) {
    TestSecurityContext testSecurityContext = lookupContext();
    if (logic.disallowsFileAccess(testSecurityContext, filename)) {
      String message = disallowedFileAccessMessage(filename);
      log("checkRead", message);
      SecurityViolationException exception = new SecurityViolationException(message);

      testSecurityContext.addFailure(exception);
      super.checkRead(filename);
      throw exception;
    }
    super.checkRead(filename);
  }

  private String disallowedFileAccessMessage(String filename) {
    return "Access to file: " + filename + " not allowed";
  }

  @Override
  public void checkWrite(String filename) {
    TestSecurityContext testSecurityContext = lookupContext();
    if (logic.disallowsFileAccess(testSecurityContext, filename)) {
      String message = disallowedFileAccessMessage(filename);
      log("checkWrite", "context: "+testSecurityContext+ " :: "+message);
      SecurityViolationException exception = new SecurityViolationException(message);

      testSecurityContext.addFailure(exception);
      super.checkWrite(filename);
      throw exception;
    }
    super.checkWrite(filename);
  }

  @Override
  public void checkDelete(String filename) {
    TestSecurityContext testSecurityContext = lookupContext();
    if (logic.disallowsFileAccess(testSecurityContext, filename)) {
      String message = disallowedFileAccessMessage(filename);
      log("checkWrite", "context: "+testSecurityContext+ " :: "+message);
      SecurityViolationException exception = new SecurityViolationException(message);

      testSecurityContext.addFailure(exception);
      super.checkDelete(filename);
      throw exception;
    }
    super.checkDelete(filename);
  }

  // Linking native libs
  //   checkLink(String lib)
  //
  // NB: I expect that we aren't going to care about file descriptors since this applies only to
  //     stdin, stdout and stderr I expect
  //   checkRead(FileDescriptor fd)
  //   checkWrite(FileDescriptor fd)

  private static void log(String methodName, String msg) {
    logger.fine("---" + methodName + ":" + msg);
  }

}
