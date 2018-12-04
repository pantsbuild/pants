package org.pantsbuild.tools.junit.impl.security;

import java.util.Objects;

/**
 * The key to look up test execution contexts with.
 */
public class ContextKey {

  static final String SEPARATOR = "\u2053";
  public ContextKey(String className, String methodName) {
    this.className = className;
    this.methodName = methodName;
  }

  public ContextKey(String className) {
    this(className, null);
  }

  static String createThreadGroupName(String className, String methodName) {
    return className + SEPARATOR + "m" + SEPARATOR + methodName + SEPARATOR + "Threads";
  }

  static ContextKey parseFromThreadGroupName(String threadGroupName) {
    String[] split = threadGroupName.split(SEPARATOR);
    if (split.length !=4 ||
        !Objects.equals(split[1], "m") ||
        !Objects.equals(split[3], "Threads")) {
      // The thread group wasn't created by the junit runner, and so it doesn't have a context key.
      return null;
    }

    // if the method name is missing it is serialized as the string null
    String methodName = split[2].equals("null") ? null : split[2];
    return new ContextKey(split[0], methodName);
  }

  private final String className;
  private final String methodName;

  @Override
  public boolean equals(Object o) {
    if (this == o) return true;
    if (o == null || getClass() != o.getClass()) return false;

    ContextKey that = (ContextKey) o;

    if (className != null ? !className.equals(that.className) : that.className != null)
      return false;
    return methodName != null ? methodName.equals(that.methodName) : that.methodName == null;
  }

  @Override
  public int hashCode() {
    return Objects.hash(className, methodName);
  }

  public String getClassName() {
    return className;
  }

  public String testNameString() {
    return className + "#" + methodName;
  }

  public String getThreadGroupName() {
    return createThreadGroupName(className, methodName);
  }

  public String getMethodName() {
    return methodName;
  }

  public boolean isSuiteKey() {
    return getMethodName() == null;
  }

  public ContextKey getSuiteKey() {
    if (isSuiteKey()) {
      return this;
    } else {
      return new ContextKey(className);
    }
  }

  @Override
  public String toString() {
    return "ContextKey{" +
        "className='" + className + '\'' +
        ", methodName='" + methodName + '\'' +
        '}';
  }
}
