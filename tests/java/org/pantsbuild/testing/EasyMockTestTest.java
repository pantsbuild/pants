// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testing;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

import com.google.common.collect.ImmutableList;
import com.google.common.reflect.TypeToken;

import org.easymock.EasyMock;
import org.easymock.IAnswer;
import org.junit.Test;

import static org.easymock.EasyMock.expectLastCall;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public class EasyMockTestTest extends EasyMockTest {

  private void assertSimplyParametrizedMockWorks(Runnable mockRunnable) {
    final AtomicBoolean ran = new AtomicBoolean(false);

    mockRunnable.run();
    expectLastCall().andAnswer(new IAnswer<Void>() {
      @Override public Void answer() {
        ran.set(true);
        return null;
      }
    });
    control.replay();

    mockRunnable.run();
    assertTrue(ran.get());
  }

  @Test
  public void testSimplyParametrizedMockViaOverload() {
    assertSimplyParametrizedMockWorks(createMock(Runnable.class));
  }

  @Test
  public void testSimplyParametrizedMock() {
    assertSimplyParametrizedMockWorks(createMock(new TypeToken<Runnable>() { }));
  }

  @Test
  public void testNestedParametrizedMock() {
    List<List<String>> list = createMock(new TypeToken<List<List<String>>>() { });
    EasyMock.expect(list.get(0)).andReturn(ImmutableList.of("jake"));
    control.replay();

    assertEquals(ImmutableList.of("jake"), list.get(0));
  }
}
