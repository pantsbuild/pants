// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.jar;

import com.google.common.io.Closer;
import java.io.Closeable;
import java.io.File;
import java.io.IOException;
import java.util.jar.JarFile;

/** Utilities for working with {@link JarFile jar files}. */
final class JarFileUtil {

  /**
   * Equivalent to {@link #openJarFile(com.google.common.io.Closer, java.io.File, boolean)}, passing
   * {@code true} for {@code verify}.
   */
  static JarFile openJarFile(Closer closer, File file) throws IOException {
    return openJarFile(closer, file, true);
  }

  /**
   * Opens a jar file and registers it with the given {@code closer}.
   *
   * @param closer A closer responsible for closing the opened jar file.
   * @param file A file pointing to a jar.
   * @param verify Whether or not to verify the jar file if it is signed.
   * @return An opened jar file.
   * @throws IOException if there is a problem opening the given {@code file} as a jar.
   */
  static JarFile openJarFile(Closer closer, File file, boolean verify) throws IOException {
    final JarFile jarFile = new JarFile(file, verify);
    closer.register(
        new Closeable() {
          @Override
          public void close() throws IOException {
            jarFile.close();
          }
        });
    return jarFile;
  }

  private JarFileUtil() {
    // utility
  }
}
