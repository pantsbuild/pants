package org.pantsbuild.tools.junit.lib.security.fileaccess;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;

import org.junit.Test;

import static org.hamcrest.CoreMatchers.is;
import static org.hamcrest.MatcherAssert.assertThat;

public class FileAccessTests {
  @Test
  public void readAFile() throws IOException {
    String pathname = "tests/resources/org/pantsbuild/tools/junit/lib/a.file";

    ArrayList<String> list = new ArrayList<>();
    list.add("ruby");
    assertThat(Files.readAllLines(Paths.get(pathname)), is(list));
  }

  @Test
  public void writeAFile() throws IOException {
    String pathname = "tests/resources/org/pantsbuild/tools/junit/lib/another.file";

    ArrayList<String> data = new ArrayList<>();
    data.add("ruby");
    Files.write(Paths.get(pathname), data);
    assertThat(Files.readAllLines(Paths.get(pathname)), is(data));
  }

  @Test
  public void deleteAFile() throws IOException {
    String pathname = "tests/resources/org/pantsbuild/tools/junit/lib/a.different.file";
    try {
      Files.delete(Paths.get(pathname));
    } catch (NoSuchFileException e) {

    }
  }

  @Test
  public void tempfile() throws IOException {
    try {
      File tempFile = File.createTempFile("my-", "-tempfile");

      tempFile.deleteOnExit();
    } catch (SecurityException e) {
      // NB: tempfile swallows the raised exception and re-throws one.
      // This catch ensures that the expected exception is reported.
      // It might be better to figure out a way to report both in cases where there is a constraint
      // violation and a separate failure cause.
    }
  }

  @Test
  public void readNonexistentRootFile() {
    String pathname = "/non-existent-file";
    boolean exists = new File(pathname).exists();
    assertThat(exists, is(false));

    Path path = Paths.get(pathname);

  }

}
