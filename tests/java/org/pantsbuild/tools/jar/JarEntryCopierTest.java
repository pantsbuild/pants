// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.jar;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.Enumeration;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.jar.JarOutputStream;
import java.util.zip.CRC32;
import java.util.zip.CheckedInputStream;

import com.google.common.base.Objects;
import com.google.common.collect.Lists;
import com.google.common.io.ByteStreams;
import com.google.common.io.Closer;
import com.google.common.io.Files;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;

public class JarEntryCopierTest {

  /**
   * Contains:
   * <PRE>
   *      0 META-INF/
   *      0 META-INF/MANIFEST.MF
   *   1300 hello-world-100.txt  # Hello World! 100 times (DEFLATED)
   *     13 hello-world.txt      # Hello World! 1 time  (STORED)
   * </PRE>
   */
  static final String A_JAR = "tests/resources/org/pantsbuild/tools/jar/a.jar";

  /**
   * Contains:
   * <PRE>
   *      0 META-INF/
   *      0 META-INF/MANIFEST.MF
   *   1500 goodbye-world-100.txt  # Goodbye World! 100 times (DEFLATED)
   *     15 goodbye-world.txt      # Hello World! 1 time (STORED)
   * </PRE>
   */
  static final String B_JAR = "tests/resources/org/pantsbuild/tools/jar/b.jar";

  /**
   * Contains:
   * <PRE>
   *      0 META-INF/
   *      0 META-INF/MANIFEST.MF
   *      0 dir/
   *   2000 dir/jar-with-a-dir-100.txt
   *     20 dir/jar-with-a-dir.txt
   * </PRE>
   */
  static final String C_JAR = "tests/resources/org/pantsbuild/tools/jar/c.jar";

  @Test
  public void testSuperShadySimple() throws Exception {
    File aJar = copyResourceToTempFile(A_JAR);

    // Copy the input file to an output file
    File jarOut = File.createTempFile("testSuperShadySimple", ".jar");
    Closer closer = Closer.create();
    try {
      JarOutputStream jos = closer.register(new JarOutputStream(new FileOutputStream(jarOut)));
      copyJarToJar(aJar, jos, true);
      jos.close();
      assertJarContents(Lists.newArrayList(aJar), jarOut);
    } finally {
      closer.close();
      jarOut.delete();
    }
  }

  @Test
  public void testSuperShadyTwoJars() throws Exception {
    File aJar = copyResourceToTempFile(A_JAR);
    File bJar = copyResourceToTempFile(B_JAR);

    // Copy the input file to an output file
    File jarOut = File.createTempFile("testSuperShadySimple", ".jar");
    Closer closer = Closer.create();
    try {
      JarOutputStream jos = closer.register(new JarOutputStream(new FileOutputStream(jarOut)));
      copyJarToJar(aJar, jos, true);
      copyJarToJar(bJar, jos, false);
      jos.close();
      assertJarContents(Lists.newArrayList(aJar, bJar), jarOut);
    } finally {
      closer.close();
      jarOut.delete();
    }
  }

  @Test
  public void testSuperShadyThreeJars() throws Exception {
    File aJar = copyResourceToTempFile(A_JAR);
    File bJar = copyResourceToTempFile(B_JAR);
    File cJar = copyResourceToTempFile(C_JAR);

    // Copy the input file to an output file
    File jarOut = File.createTempFile("testSuperShadySimple", ".jar");
    Closer closer = Closer.create();
    try {
      JarOutputStream jos = closer.register(new JarOutputStream(new FileOutputStream(jarOut)));
      copyJarToJar(aJar, jos, true);
      copyJarToJar(bJar, jos, false);
      copyJarToJar(cJar, jos, false);
      jos.close();
      assertJarContents(Lists.newArrayList(aJar, bJar, cJar), jarOut);
    } finally {
      closer.close();
      jarOut.delete();
    }
  }

  private static final class ChecksumEntry {
    private final JarEntry entry;
    private final long checksumValue;

    public ChecksumEntry(JarEntry entry, long checksumValue) {
      this.entry = entry;
      this.checksumValue = checksumValue;
    }

    @Override
    public boolean equals(Object o) {

      if (this == o) {
        return true;
      }
      if (o == null || getClass() != o.getClass()) {
        return false;
      }

      ChecksumEntry that = (ChecksumEntry) o;

      return Objects.equal(checksumValue, that.checksumValue)
          && Objects.equal(entry.getName(), that.entry.getName());
    }

    @Override
    public int hashCode() {
      return Objects.hashCode(entry.getName(), checksumValue);
    }

    @Override
    public String toString() {
      return entry.getName() + ":" + checksumValue;
    }
  }

  private void copyJarToJar(File jarFileIn, JarOutputStream jos, boolean copyManifest)
      throws IOException {
    Closer closer = Closer.create();
    try {
      JarFile jarIn = JarFileUtil.openJarFile(closer, jarFileIn);
      Enumeration<JarEntry> en = jarIn.entries();
      while (en.hasMoreElements()) {
        JarEntry entry = en.nextElement();
        if (!copyManifest
            && ("META-INF/".equals(entry.getName())
                || "META-INF/MANIFEST.MF".equals(entry.getName()))) {
          continue;
        }
        JarEntryCopier.copyEntry(jos, entry.getName(), jarIn, entry);
      }
    } finally {
      closer.close();
    }
  }

  private void assertJarContents(List<File> jarsIn, File jarOut) throws Exception {
    Set<ChecksumEntry> inputEntries = new LinkedHashSet<ChecksumEntry>();
    for (File jarIn : jarsIn) {
      inputEntries.addAll(getChecksummedEntries(jarIn));
    }
    Set<ChecksumEntry> outputEntries = getChecksummedEntries(jarOut);
    assertJarContents(inputEntries, outputEntries);
  }

  private void assertJarContents(Set<ChecksumEntry> inputEntries,
      Set<ChecksumEntry> outputEntries) {
    assertEquals(inputEntries, outputEntries);
  }

  private Set<ChecksumEntry> getChecksummedEntries(File file) throws Exception {
    Set<ChecksumEntry> result = new LinkedHashSet<ChecksumEntry>();
    Closer closer = Closer.create();
    try {
      JarFile jarFile = JarFileUtil.openJarFile(closer, file);
      Enumeration<JarEntry> en = jarFile.entries();
      while (en.hasMoreElements()) {
        JarEntry entry = en.nextElement();
        long jarFileCrc = entry.getCrc();

        // Make sure the content checksum matches the checksum in the file.
        // This may be super paranoid, maybe the library already checks it?
        CheckedInputStream is = closer.register(
            new CheckedInputStream(jarFile.getInputStream(entry),
                new CRC32())
        );
        // Fully consume the input.
        ByteStreams.copy(is, ByteStreams.nullOutputStream());

        assertEquals(jarFileCrc, is.getChecksum().getValue());

        ChecksumEntry csEntry = new ChecksumEntry(entry, jarFileCrc);
        assertFalse(result.contains(csEntry));
        result.add(csEntry);
      }
    } finally {
      closer.close();
    }
    return result;
  }

  private File copyResourceToTempFile(String resourcePath) throws Exception {
    File resourcePathFile = new File(resourcePath);
    // Assumes the name is <prefix>.jar
    String[] nameParts = resourcePathFile.getName().split("\\.");
    assertEquals(2, nameParts.length);
    File tempFile = File.createTempFile("testSuperShadySimple" + nameParts[0], ".jar");
    tempFile.deleteOnExit();
    Files.copy(resourcePathFile, tempFile);
    return tempFile;
  }
}
