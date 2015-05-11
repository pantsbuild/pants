// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testing;

import com.google.common.reflect.TypeToken;
import com.google.common.testing.TearDown;

import org.easymock.IMocksControl;
import org.junit.Before;

import static org.easymock.EasyMock.createControl;

/**
 * A baseclass for tests that use EasyMock.
 *
 * A new {@link IMocksControl control} is set up before each test and the mocks created and
 * replayed with it are verified during tear down.
 */
public class EasyMockTest extends TearDownTestCase {
  protected IMocksControl control;

  /**
   * Creates an EasyMock {@link #control} for tests to use that will be automatically
   * {@link IMocksControl#verify() verified} on tear down.
   *
   * This {@code @Before} will be invoked by the junit runner test infrastructure and is not
   * intended to be called by test subclasses.
   */
  @Before
  public final void setupControl() {
    control = createControl();
    addTearDown(new TearDown() {
      @Override
      public void tearDown() {
        control.verify();
      }
    });
  }

  /**
   * Creates an EasyMock mock with this test's control.
   *
   * Will be {@link IMocksControl#verify() verified} in a tear down.
   */
  protected <T> T createMock(Class<T> token) {
    return createMock(TypeToken.of(token));
  }

  /**
   * Creates an EasyMock mock with this test's control.
   *
   * Allows for mocking of parameterized types without all the unchecked conversion warnings in a
   * safe way.
   *
   * Will be {@link IMocksControl#verify() verified} in a tear down.
   */
  protected <T> T createMock(TypeToken<T> token) {
    @SuppressWarnings("unchecked")
    Class<T> rawType = (Class<T>) token.getRawType();
    return control.createMock(rawType);
  }
}