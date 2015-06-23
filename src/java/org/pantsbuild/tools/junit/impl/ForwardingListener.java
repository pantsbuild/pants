// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.util.List;

import com.google.common.collect.Lists;

import org.junit.runner.Description;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;

/**
 * A run listener that forwards all events to a sequence of registered listeners.
 */
class ForwardingListener extends RunListener implements ListenerRegistry {
  /**
   * Fires an event to a listener.
   *
   * @param <E> The type of exception thrown when firing this event.
   */
  private interface Event<E extends Exception> {
    void fire(RunListener listener) throws E;
  }

  private final List<RunListener> listeners = Lists.newArrayList();

  @Override
  public void addListener(RunListener listener) {
    listeners.add(listener);
  }

  private <E extends Exception> void fire(Event<E> dispatcher) throws E {
    for (RunListener listener : listeners) {
      dispatcher.fire(listener);
    }
  }

  @Override
  public void testRunStarted(final Description description) throws Exception {
    fire(new Event<Exception>() {
      @Override public void fire(RunListener listener) throws Exception {
        listener.testRunStarted(description);
      }
    });
  }

  @Override
  public void testRunFinished(final Result result) throws Exception {
    fire(new Event<Exception>() {
      @Override public void fire(RunListener listener) throws Exception {
        listener.testRunFinished(result);
      }
    });
  }

  @Override
  public void testStarted(final Description description) throws Exception {
    fire(new Event<Exception>() {
      @Override public void fire(RunListener listener) throws Exception {
        listener.testStarted(description);
      }
    });
  }

  @Override
  public void testIgnored(final Description description) throws Exception {
    fire(new Event<Exception>() {
      @Override public void fire(RunListener listener) throws Exception {
        listener.testIgnored(description);
      }
    });
  }

  @Override
  public void testFailure(final Failure failure) throws Exception {
    fire(new Event<Exception>() {
      @Override public void fire(RunListener listener) throws Exception {
        listener.testFailure(failure);
      }
    });
  }

  @Override
  public void testFinished(final Description description) throws Exception {
    fire(new Event<Exception>() {
      @Override public void fire(RunListener listener) throws Exception {
        listener.testFinished(description);
      }
    });
  }

  @Override
  public void testAssumptionFailure(final Failure failure) {
    fire(new Event<RuntimeException>() {
      @Override public void fire(RunListener listener) {
        listener.testAssumptionFailure(failure);
      }
    });
  }
}
