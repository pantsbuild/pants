// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import org.junit.runner.notification.RunListener;

/**
 * Registers {@link RunListener RunListeners} for callbacks during a a test run session.
 */
interface ListenerRegistry {

  /**
   * Registers the {@code listener} for callbacks.
   *
   * @param listener The listener to register.
   */
  void addListener(RunListener listener);
}
