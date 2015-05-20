package org.pantsbuild.testproject.dummies;

// intentional warning. see JvmExamplesCompileIntegrationTest#test_log_level
import sun.security.x509.X500Name;

/**
 * A simple example with an error and a warning to use in tests
 **/
public class CompilationFailure {
  public static void main(String[] args) {
    System.out.println("Hello World!");
    // intentional error. see JvmExamplesCompileIntegrationTest#test_log_level
    System2.out.println("Hello World!");
  }
}