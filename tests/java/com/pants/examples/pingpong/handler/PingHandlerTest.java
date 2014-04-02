// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.pingpong.handler;

import org.junit.Before;
import org.junit.Test;

import com.twitter.common.base.Closure;
import com.twitter.common.testing.easymock.EasyMockTest;

public class PingHandlerTest extends EasyMockTest {

  private Closure<String> client;
  private PingHandler handler;

  @Before
  public void setUp() {
    client = createMock(new Clazz<Closure<String>>() { });
    handler = new PingHandler(client);
  }

  @Test
  public void testDefaultTtl() {
    client.execute("/ping/hello/" + (PingHandler.DEFAULT_TTL - 1));

    control.replay();

    handler.incoming("hello");
  }

  @Test
  public void testWithTtl() {
    client.execute("/ping/hello/1");

    control.replay();

    handler.incoming("hello", 2);
    handler.incoming("hello", 1);
  }
}
