// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.jar;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.jar.JarOutputStream;
import java.util.zip.CRC32;
import java.util.zip.CheckedInputStream;
import java.util.zip.ZipEntry;

import com.google.common.base.Objects;
import com.google.common.collect.Lists;
import com.google.common.io.ByteStreams;
import com.google.common.io.Closer;
import com.google.common.io.Files;

import org.junit.Test;
import org.pantsbuild.buck.util.zip.ZipConstants;
import org.pantsbuild.buck.util.zip.ZipScrubber;

import static org.junit.Assert.assertArrayEquals;
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

  // Identical to A_JAR but with constant timestamps.
  static final String A_JAR_SCRUBBED = "tests/resources/org/pantsbuild/tools/jar/a.scrubbed.jar";

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
  public void testScrubTimestamps() throws Exception {
    JarFileToCopy aJar = new JarFileToCopy(copyResourceToTempFile(A_JAR), true);

    // Copy the input file to an output file
    File jarOut = File.createTempFile("testSuperShadySimple", ".jar");
    Closer closer = Closer.create();
    try {
      JarOutputStream jos = closer.register(new JarOutputStream(new FileOutputStream(jarOut)));
      copyJarToJar(aJar, jos);
      jos.close();
      ZipScrubber.scrubZip(jarOut.toPath());
      assertJarContents(Lists.newArrayList(aJar), true, jarOut);

      // Because we've scrubbed the jar, we expect it to be byte-for-byte identical to our golden:
      byte[] expected = Files.toByteArray(new File(A_JAR_SCRUBBED));
      byte[] actual = Files.toByteArray(jarOut);
      assertArrayEquals(expected, actual);
    } finally {
      closer.close();
      jarOut.delete();
    }
  }

  @Test
  public void testSuperShadySimple() throws Exception {
    JarFileToCopy aJar = new JarFileToCopy(copyResourceToTempFile(A_JAR), true);

    // Copy the input file to an output file
    File jarOut = File.createTempFile("testSuperShadySimple", ".jar");
    Closer closer = Closer.create();
    try {
      JarOutputStream jos = closer.register(new JarOutputStream(new FileOutputStream(jarOut)));
      copyJarToJar(aJar, jos);
      jos.close();
      assertJarContents(Lists.newArrayList(aJar), false, jarOut);
    } finally {
      closer.close();
      jarOut.delete();
    }
  }

  @Test
  public void testSuperShadyTwoJars() throws Exception {
    JarFileToCopy aJar = new JarFileToCopy(copyResourceToTempFile(A_JAR), true);
    JarFileToCopy bJar = new JarFileToCopy(copyResourceToTempFile(B_JAR), false);

    // Copy the input file to an output file
    File jarOut = File.createTempFile("testSuperShadySimple", ".jar");
    Closer closer = Closer.create();
    try {
      JarOutputStream jos = closer.register(new JarOutputStream(new FileOutputStream(jarOut)));
      copyJarToJar(aJar, jos);
      copyJarToJar(bJar, jos);
      jos.close();
      assertJarContents(Lists.newArrayList(aJar, bJar), false, jarOut);
    } finally {
      closer.close();
      jarOut.delete();
    }
  }

  @Test
  public void testSuperShadyThreeJars() throws Exception {
    JarFileToCopy aJar = new JarFileToCopy(copyResourceToTempFile(A_JAR), true);
    JarFileToCopy bJar = new JarFileToCopy(copyResourceToTempFile(B_JAR), false);
    JarFileToCopy cJar = new JarFileToCopy(copyResourceToTempFile(C_JAR), false);

    // Copy the input file to an output file
    File jarOut = File.createTempFile("testSuperShadySimple", ".jar");
    Closer closer = Closer.create();
    try {
      JarOutputStream jos = closer.register(new JarOutputStream(new FileOutputStream(jarOut)));
      copyJarToJar(aJar, jos);
      copyJarToJar(bJar, jos);
      copyJarToJar(cJar, jos);
      jos.close();
      assertJarContents(Lists.newArrayList(aJar, bJar, cJar), false, jarOut);
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
          && Objects.equal(entry.getName(), that.entry.getName())
          && Objects.equal(entry.getTime(), that.entry.getTime());
    }

    @Override
    public int hashCode() {
      return Objects.hashCode(entry.getName(), entry.getTime(), checksumValue);
    }

    @Override
    public String toString() {
      return entry.getName() + ":" + checksumValue + " @ " + entry.getTime();
    }
  }

  private void copyJarToJar(JarFileToCopy jarFileIn, JarOutputStream jos)
      throws IOException {
    Closer closer = Closer.create();
    try {
      JarFile jarIn = JarFileUtil.openJarFile(closer, jarFileIn.file);
      Enumeration<JarEntry> en = jarIn.entries();
      while (en.hasMoreElements()) {
        JarEntry entry = en.nextElement();
        if (jarFileIn.shouldCopy(entry)) {
          JarEntryCopier.copyEntry(jos, entry.getName(), jarIn, entry);
        }
      }
    } finally {
      closer.close();
    }
  }

  private void assertJarContents(
      List<JarFileToCopy> jarsIn,
      boolean expectZipConstantDosTime,
      File jarOut
  ) throws Exception {
    LinkedHashSet<ChecksumEntry> inputEntries = new LinkedHashSet<ChecksumEntry>();
    for (JarFileToCopy jarIn : jarsIn) {
      for (ChecksumEntry entry : getChecksummedEntries(jarIn)) {
        if (expectZipConstantDosTime) {
          // Something about the Java Date API means that if we use entry.setTime,
          // we drift by a few milliseconds.
          // So we forcibly set the DOS value by reflection.
          // This is, indeed, awful.
          Field field = ZipEntry.class.getDeclaredField("xdostime");
          field.setAccessible(true);
          field.setLong(entry.entry, ZipConstants.DOS_FAKE_TIME);
        }
        inputEntries.add(entry);
      }
    }
    LinkedHashSet<ChecksumEntry> outputEntries =
        getChecksummedEntries(new JarFileToCopy(jarOut, true));
    // Ordering of entries matters for determinism, so we compare Lists not Sets.
    assertEquals(new ArrayList<>(inputEntries), new ArrayList<>(outputEntries));
  }

  static class JarFileToCopy {
    File file;
    boolean includeManifest;

    public JarFileToCopy(File file, boolean includeManifest) {
      this.file = file;
      this.includeManifest = includeManifest;
    }

    public boolean shouldCopy(JarEntry entry) {
      return includeManifest ||
          !(("META-INF/".equals(entry.getName()) ||
              "META-INF/MANIFEST.MF".equals(entry.getName())));
    }
  }

  private LinkedHashSet<ChecksumEntry> getChecksummedEntries(JarFileToCopy file) throws Exception {
    LinkedHashSet<ChecksumEntry> result = new LinkedHashSet<ChecksumEntry>();
    Closer closer = Closer.create();
    try {
      JarFile jarFile = JarFileUtil.openJarFile(closer, file.file);
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

        if (file.shouldCopy(entry)) {
          ChecksumEntry csEntry = new ChecksumEntry(entry, jarFileCrc);
          assertFalse(result.contains(csEntry));
          result.add(csEntry);
        }
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
