package org.pantsbuild.stripjar;

import io.github.zlika.reproducible.ManifestStripper;
import io.github.zlika.reproducible.ZipStripper;
import java.io.File;
import java.io.IOException;
import java.nio.file.Path;
import java.nio.file.Paths;

public class StripJar {
  public static void main(String[] args) {
    ZipStripper stripper =
        new ZipStripper().addFileStripper("META-INF/MANIFEST.MF", new ManifestStripper());

    Path inputPath = Paths.get(args[0]);
    Path outputPath = Paths.get(args[1]);
    File outputDirectory = outputPath.toFile();

    if (!outputDirectory.exists()) outputDirectory.mkdir();

    for (int i = 2; i < args.length; i++) {
      String jarName = args[i];
      File input = inputPath.resolve(jarName).toFile();
      File output = outputPath.resolve(jarName).toFile();

      try {
        stripper.strip(input, output);
      } catch (IOException ex) {
        System.err.println(ex.toString());
        System.exit(1);
      }
    }
  }
}
