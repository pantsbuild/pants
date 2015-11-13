// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import org.junit.Test;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public class UtilTest {

  @Test
  public void testSanitizeSuiteName() {
    assertEquals("com.foo.bar.ClassName", Util.sanitizeSuiteName("com.foo.bar.ClassName"));
    assertEquals("com.foo.bar.ClassName", Util.sanitizeSuiteName("com.foo.bar.ClassName...."));
    assertEquals("com.foo.bar.ClassName", Util.sanitizeSuiteName("com.foo.bar.ClassName."));
    assertEquals("This-is-a-free-form-sentence",
        Util.sanitizeSuiteName("This is a free-form sentence."));
    assertEquals("This-sentence-has-these-numbers-in-it--1-2-3-4-5-6-7-8-9",
        Util.sanitizeSuiteName("This sentence has these numbers in it: 1 2 3 4 5 6 7 8 9."));
    assertEquals("Soy-una-prueba-pequeña-para-palabras-en-Español",
        Util.sanitizeSuiteName("Soy una prueba pequeña para palabras en Español."));
    // The regex only filters out English punctuations, because those are the ones that are
    // potentially dangerous as file patterns. Thus, '?' is filtered but '¿' is not.
    assertEquals("¿Qué-", Util.sanitizeSuiteName("¿Qué?"));
    // Test every English letter.
    assertEquals("Thequickbrownfoxjumpedoverthelazydog",
        Util.sanitizeSuiteName("Thequickbrownfoxjumpedoverthelazydog."));
    assertEquals("이것은-한국인", Util.sanitizeSuiteName("이것은 한국인..."));
    String sanitizedPunctuations = Util.sanitizeSuiteName("`~!@#$%^&*()+-=[]{}\\/<>|");
    assertTrue("Sanitized punctions were't converted to all hyphens: " + sanitizedPunctuations,
        sanitizedPunctuations.matches("^[-]+$"));
  }
}
