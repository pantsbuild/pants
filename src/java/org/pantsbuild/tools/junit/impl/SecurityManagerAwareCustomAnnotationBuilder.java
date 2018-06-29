package org.pantsbuild.tools.junit.impl;

import org.junit.internal.builders.AllDefaultPossibilitiesBuilder;
import org.junit.internal.builders.AnnotatedBuilder;
import org.junit.internal.builders.JUnit4Builder;
import org.junit.runner.Runner;
import org.pantsbuild.tools.junit.impl.security.JunitSecViolationReportingManager;
import org.pantsbuild.tools.junit.impl.security.SecurityManagedRunner;

/**
 * Needed to support retrying flaky tests as well as add support for running scala tests.
 * Using method overriding, gives us access to code in JUnit4 that cannot be customized
 * in a simpler way.
 */
public class SecurityManagerAwareCustomAnnotationBuilder extends AllDefaultPossibilitiesBuilder {

  private final CustomAnnotationBuilder underlyingBuilder;
  private final JunitSecViolationReportingManager securityManager;

  SecurityManagerAwareCustomAnnotationBuilder(
      CustomAnnotationBuilder underlyingBuilder,
      JunitSecViolationReportingManager securityManager) {
    super(true);
    this.underlyingBuilder = underlyingBuilder;
    this.securityManager = securityManager;
  }

  @Override
  public JUnit4Builder junit4Builder() {
    return new JUnit4Builder() {
      @Override
      public Runner runnerForClass(Class<?> testClass) throws Throwable {
        return new SecurityManagedRunner(
            underlyingBuilder.junit4Builder().runnerForClass(testClass),
            securityManager);
      }
    };
  }

  // override annotated builder to "fake" the scala test junit runner for scala tests
  @Override
  protected AnnotatedBuilder annotatedBuilder() {
    return new CustomAnnotationBuilder.ScalaTestAnnotatedBuilder(this);
  }
}
