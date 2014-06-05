// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Illustrate using Thrift-generated code from Java.

package com.pants.examples.usezip;

import org.junit.Test;
import org.junit.Assert;

import com.pants.examples.zip.A;
import com.pants.examples.zip.B;
import com.pants.examples.zip.greeting.Hello;
import com.pants.examples.tar.Ta;
import com.pants.examples.tar.Tb;
import com.pants.examples.tar.greeting.Thello;

public class UseZipTest {
  @Test
  public void zippedProtosTest() {
    A.AMessage.newBuilder().setExample("Apple").setUnicode('A').build();
    B.BMessage.newBuilder().setName("Bee").setType("Insect").setLegs(6);
    Hello.HelloMessage.newBuilder().setGreeting("Salutations!").setEnthusiasm(27);
    Ta.AMessage.newBuilder().setExample("Ampersand").setUnicode('&').build();
  }
}


