// =================================================================================================
// Copyright 2013 Twitter, Inc.
// -------------------------------------------------------------------------------------------------
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this work except in compliance with the License.
// You may obtain a copy of the License in the LICENSE file, or at:
//
//  http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// =================================================================================================

package com.twitter.common.examples.pingpong.handler;

import org.junit.Before;
import org.junit.Test;

import com.twitter.common.base.Closure;
import com.twitter.common.testing.EasyMockTest;

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
