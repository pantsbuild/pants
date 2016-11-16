// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import org.junit.Test;
import org.junit.runner.Description;
import org.pantsbuild.tools.junit.lib.MockJUnit3Test;
import org.pantsbuild.tools.junit.lib.MockRunWithTest;
import org.pantsbuild.tools.junit.lib.MockScalaTest;
import org.pantsbuild.tools.junit.lib.MockTest1;
import org.pantsbuild.tools.junit.lib.NotAScalaTest;
import org.pantsbuild.tools.junit.lib.NotATestAbstractClass;
import org.pantsbuild.tools.junit.lib.NotATestInterface;
import org.pantsbuild.tools.junit.lib.NotATestNoPublicConstructor;
import org.pantsbuild.tools.junit.lib.NotATestNoRunnableMethods;
import org.pantsbuild.tools.junit.lib.NotATestNonzeroArgConstructor;
import org.pantsbuild.tools.junit.lib.NotATestPrivateClass;
import org.pantsbuild.tools.junit.lib.UnannotatedTestClass;
import org.pantsbuild.tools.junit.lib.XmlReportFirstTestIngoredTest;
import org.pantsbuild.tools.junit.lib.XmlReportIgnoredTestSuiteTest;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class UtilTest {

  @Test
  public void testIsIgnoredClass() {
    assertTrue(Util.isIgnored(XmlReportIgnoredTestSuiteTest.class));
    assertFalse(Util.isIgnored(MockTest1.class));
  }

  @Test
  public void testIsIgnoredDescription() throws Exception {
    assertTrue(Util.isIgnored(getDescription(XmlReportFirstTestIngoredTest.class,
        "testXmlIgnored")));
    assertFalse(Util.isIgnored(getDescription(XmlReportFirstTestIngoredTest.class,
        "testXmlPassing")));
  }

  @Test
  public void testIsRunnableDescription() throws Exception {
    assertFalse(Util.isRunnable(getDescription(XmlReportFirstTestIngoredTest.class,
        "testXmlIgnored")));
    assertTrue(Util.isRunnable(getDescription(XmlReportFirstTestIngoredTest.class,
        "testXmlPassing")));
  }

  @Test
  public void testGetPantsFriendlyDisplayName() throws Exception {
    assertEquals("org.pantsbuild.tools.junit.lib.MockTest1#testMethod11",
        Util.getPantsFriendlyDisplayName(getDescription(MockTest1.class,
        "testMethod11")));
    assertEquals("Vanilla Name",
        Util.getPantsFriendlyDisplayName(Description.createSuiteDescription("Vanilla Name")));
  }

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

  @Test
  public void testIsUsingCustomRunner() {
    assertTrue(Util.isUsingCustomRunner(MockRunWithTest.class));
    assertFalse(Util.isUsingCustomRunner(MockTest1.class));
  }

  @Test
  public void testIsJunit3() {
    assertTrue(Util.isJunit3Test(MockJUnit3Test.class));
    assertFalse(Util.isJunit3Test(MockTest1.class));
  }

  @Test
  public void testIsRunnableClass() {
    assertTrue(Util.isRunnable(MockJUnit3Test.class));
    assertFalse(Util.isRunnable(XmlReportIgnoredTestSuiteTest.class));
  }

  @Test
  public void testIsATestClass() {
    assertTrue(Util.isTestClass(MockJUnit3Test.class));
    assertTrue(Util.isTestClass(MockRunWithTest.class));
    assertTrue(Util.isTestClass(UnannotatedTestClass.class));
    assertTrue(Util.isTestClass(MockScalaTest.class));
    assertFalse(Util.isTestClass(NotATestAbstractClass.class));
    assertFalse(Util.isTestClass(NotATestNonzeroArgConstructor.class));
    assertFalse(Util.isTestClass(NotATestNoPublicConstructor.class));
    assertFalse(Util.isTestClass(NotATestInterface.class));
    assertFalse(Util.isTestClass(NotATestNoRunnableMethods.class));
    assertFalse(Util.isTestClass(NotATestPrivateClass.class));
    assertFalse(Util.isTestClass(NotAScalaTest.class));

    // Even though this is ignored it should still be considered a Test
    assertTrue(Util.isTestClass(XmlReportIgnoredTestSuiteTest.class));
  }

  private Description getDescription(Class<?> clazz, String methodName) throws Exception {
    return Description.createTestDescription(
        clazz, methodName, clazz.getMethod(methodName).getAnnotations());
  }
}
