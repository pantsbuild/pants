package org.pantsbuild.tools.junit.impl.security;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * The context that wraps a test or suite so that the security manager can determine what to do.
 */
public class TestSecurityContext {

  private final ContextKey contextKey;
  private final ThreadGroup threadGroup;
  private Map<String, TestSecurityContext> children = new HashMap<>();
  private final List<Exception> failures = new ArrayList<>();

  static TestSecurityContext newSuiteContext(String classname) {
    return new TestSecurityContext(classname);
  }

  static TestSecurityContext newTestCaseContext(
      ContextKey contextKey,
      TestSecurityContext suiteContext) {
    return new TestSecurityContext(contextKey, suiteContext);
  }

  static TestSecurityContext newTestCaseContext(
      String className,
      String methodName,
      TestSecurityContext parent) {
    return new TestSecurityContext(className, methodName, parent);
  }

  private static ThreadGroup createThreadGroup(ContextKey contextKey, TestSecurityContext parent) {
    return new ThreadGroup(parent.getThreadGroup(), contextKey.getThreadGroupName());
  }

  private TestSecurityContext(ContextKey contextKey, TestSecurityContext parent) {
    this.contextKey = contextKey;
    if (parent == null) {
      throw new IllegalArgumentException("parent cannot be null: " + contextKey);
    }
    this.threadGroup = createThreadGroup(contextKey, parent);
  }

  private TestSecurityContext(String className, String methodName, TestSecurityContext parent) {
    this(new ContextKey(className, methodName), parent);
  }

  private TestSecurityContext(String className) {
    contextKey = new ContextKey(className, null);
    threadGroup = new ThreadGroup(contextKey.getThreadGroupName());
  }

  public ContextKey getContextKey() {
    return contextKey;
  }

  public String getClassName() {
    return contextKey.getClassName();
  }

  public void addFailure(Exception ex) {
    failures.add(ex);
  }

  public List<Exception> getFailures() {
    List<Exception> failures = new ArrayList<>();
    failures.addAll(this.failures);
    return failures;
  }

  public boolean hadFailures() {
    return !getFailures().isEmpty();
  }

  public Exception firstFailure() {
    return getFailures().get(0);
  }

  public boolean hasActiveThreads() {
    boolean activeCountNotEmpty = getThreadGroup().activeCount() > 0;
    if (activeCountNotEmpty) {
      return activeCountNotEmpty;
    }
    for (TestSecurityContext testSecurityContext : children.values()) {
      if (testSecurityContext.hasActiveThreads()) {
        return true;
      }
    }
    return false;
  }

  public ThreadGroup getThreadGroup() {
    return threadGroup;
  }

  public synchronized void addChild(TestSecurityContext testSecurityContext) {
    children.put(testSecurityContext.getContextKey().getMethodName(), testSecurityContext);
  }

  public boolean hasNoChildren() {
    return children.isEmpty();
  }

  public TestSecurityContext getChild(String methodName) {
    return children.get(methodName);
  }

  public boolean isSuite() {
    return getContextKey().isSuiteKey();
  }

  public String toString() {
    return "TestSecurityContext{" +
        "contextKey=" + contextKey +
        ", threadGroup=" + threadGroup +
        ", children=" + children +
        '}';
  }
}
