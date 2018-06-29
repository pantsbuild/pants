package org.pantsbuild.junit.security;

/**
 * Raised and reported when a test case or suite violates one of the constraints the security
 * manager was configured with.
 */
public class SecurityViolationException extends SecurityException {

  public SecurityViolationException(String message) {
    super(message);
  }
}
