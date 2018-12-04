package org.pantsbuild.tools.junit.impl;

import org.junit.internal.builders.AllDefaultPossibilitiesBuilder;
import org.junit.internal.builders.AnnotatedBuilder;
import org.junit.internal.builders.JUnit4Builder;
import org.junit.runner.Runner;
import org.pantsbuild.tools.junit.impl.security.JunitSecViolationReportingManager;
import org.pantsbuild.tools.junit.impl.security.SecurityManagedRunner;

/**
 * TODO This could be a subclass of CustomAnnotationBuilder instead of a wrapper.
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
  // passing this rather than the underlying builder to access the junit4Builder
  @Override
  protected AnnotatedBuilder annotatedBuilder() {
    return new CustomAnnotationBuilder.ScalaTestAnnotatedBuilder(this);
  }
}
