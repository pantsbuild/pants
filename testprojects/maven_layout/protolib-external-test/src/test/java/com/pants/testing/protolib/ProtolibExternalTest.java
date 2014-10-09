package com.pants.testing.protolib;


import com.squareup.testing.protolib.External;
import org.junit.Test;

import static org.junit.Assert.assertEquals;


public class ProtolibExternalTest {

  @Test
  public void testApp() {
    External.ExternalMessage message = External.ExternalMessage.newBuilder().setMessageType(1)
        .setMessasgeContent("Hello World!").build();
    assertEquals(1, message.getMessageType());
    assertEquals("Hello World!", message.getMessasgeContent());
  }
}
