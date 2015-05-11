// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testing;

import com.google.common.testing.TearDown;
import com.google.common.testing.TearDownStack;

import org.junit.After;
import org.junit.Before;

/**
 * A baseclass for tests that allows use of inline {@link TearDown TearDowns} as an alternative to
 * {@code @Before} and {@code @After} resource management.
 */
public class TearDownTestCase {

  private TearDownStack tearDowns;

  @Before
  public final void setUpTearDowns() {
    tearDowns = new TearDownStack();
  }

  @After
  public final void runTearDowns() {
    tearDowns.runTearDown();
  }

  /**
   * Adds {@code tearDown} to the list of tear downs to ensure are executed.
   *
   * The tear downs registered via this method will be execute in LIFO order.
   *
   * @param tearDown The {@code tearDown} to ensure is run.
   */
  protected final void addTearDown(TearDown tearDown) {
    tearDowns.addTearDown(tearDown);
  }
}