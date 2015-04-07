package org.pantsbuild.testing.protolib;


import com.squareup.testing.protolib.External;
import org.junit.Test;

import static org.junit.Assert.assertEquals;


public class ProtolibExternalTest {

  @Test
  public void testApp() {
    External.ExternalMessage message = External.ExternalMessage.newBuilder().setMessageType(1)
        .setMessageContent("Hello World!").build();
    assertEquals(1, message.getMessageType());
    assertEquals("Hello World!", message.getMessageContent());
  }
}
