// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.squareup.squarepants.pants_test_app.query_subjects;

import org.junit.Test;
import static org.junit.Assert.assertTrue;

public class TestAnotherFile {
    @Test public void testAnotherFile() {
      assertTrue(new AnotherFile().checkMyJavaFile());
    }
}
