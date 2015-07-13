// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.duplicates;

import java.io.BufferedReader;
import java.io.InputStreamReader;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

/**
 * Relies on textfile.txt, whose fully qualified resource name is duplicated in onedir.
 */
public class SecondTest {

    @Test
    public void testTextFile() throws Exception {
        BufferedReader in = new BufferedReader(new InputStreamReader(
                getClass().getResourceAsStream("/org/pantsbuild/duplicates/textfile.txt")
        ));
        assertEquals("Textfile Two.", in.readLine());
        in.close();
    }

}
