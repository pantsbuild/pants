package org.pantsbuild.zinc.compiler

import com.google.common.hash.{HashCode, Hashing}
import java.io.File
import java.nio.charset.StandardCharsets
import java.nio.file.{FileAlreadyExistsException, Files, StandardCopyOption}
import java.util.concurrent.Callable
import org.pantsbuild.zinc.cache.Cache
import org.pantsbuild.zinc.compiler.CompilerUtils.newScalaCompiler
import org.pantsbuild.zinc.compiler.InputUtils.ScalaJars
import org.pantsbuild.zinc.scalautil.ScalaUtils
import sbt.internal.inc.ZincUtil
import xsbti.compile.{ClasspathOptionsUtil, Compilers}

class CompilerCache(limit: Int) {
  val cache = Cache[HashCode, Compilers](limit)

  def make(scalaJars: ScalaJars, javaHome: Option[File], compiledBridgeJar: DigestedFile): Compilers = {
    val instance = ScalaUtils.scalaInstance(scalaJars.compiler.file, scalaJars.extra.map { _.file }, scalaJars.library.file)
    ZincUtil.compilers(instance, ClasspathOptionsUtil.auto, javaHome, newScalaCompiler(instance, compiledBridgeJar.file))
  }

  def get(compilerCacheDir: File, scalaJars: ScalaJars, javaHome: Option[File], compiledBridgeJar: DigestedFile): Compilers = {
    val cacheKeyBuilder = Hashing.sha256().newHasher();

    for (file <- Seq(scalaJars.compiler, scalaJars.library) ++ scalaJars.extra) {
      cacheKeyBuilder.putBytes(HashCode.fromString(file.digest.fingerprintHex).asBytes)
      cacheKeyBuilder.putLong(file.digest.sizeBytes)
    }

    javaHome match {
      case Some(file) => cacheKeyBuilder.putString(file.getCanonicalPath, StandardCharsets.UTF_8)
      case None => {}
    }

    val cacheKey = cacheKeyBuilder.hash()
    cache.get(cacheKey, new Callable[Compilers] { def call(): Compilers = {
      val versionedCompilerCacheDir = new File(compilerCacheDir, cacheKey.toString)

      val newScalaCompilerJar = CompilerCache.rename(scalaJars.compiler, versionedCompilerCacheDir, "scala-compiler")
      val newScalaLibraryJar = CompilerCache.rename(scalaJars.library, versionedCompilerCacheDir, "scala-library")
      val newScalaExtraJars = scalaJars.extra.map { CompilerCache.rename(_, versionedCompilerCacheDir, "scala-extra") }
      val newCompiledBridgeJar = CompilerCache.rename(compiledBridgeJar, versionedCompilerCacheDir, "compiled-bridge")
      if (!versionedCompilerCacheDir.exists) {
        val tempVersionedCompilerCacheDir = compilerCacheDir.toPath
          .resolve(s"${ cacheKey.toString }.tmp")
        Files.createDirectories(tempVersionedCompilerCacheDir)
        Files.copy(scalaJars.compiler.file.toPath, tempVersionedCompilerCacheDir.resolve(newScalaCompilerJar.file.getName))
        Files.copy(scalaJars.library.file.toPath, tempVersionedCompilerCacheDir.resolve(newScalaLibraryJar.file.getName))
        for ((oldExtra, newExtra) <- scalaJars.extra zip newScalaExtraJars)
          Files.copy(oldExtra.file.toPath, tempVersionedCompilerCacheDir.resolve(newExtra.file.getName))
        Files.copy(compiledBridgeJar.file.toPath, tempVersionedCompilerCacheDir.resolve(newCompiledBridgeJar.file.getName))
        try {
          Files.move(tempVersionedCompilerCacheDir, versionedCompilerCacheDir.toPath, StandardCopyOption.ATOMIC_MOVE)
        } catch {
          case _: FileAlreadyExistsException => {
            // Ignore - trust that someone else atomically created the directory properly
          }
        }
      }

      make(ScalaJars(newScalaCompilerJar, newScalaLibraryJar, newScalaExtraJars), javaHome, newCompiledBridgeJar)
    }})
  }
}

object CompilerCache {
  def rename(file: DigestedFile, dir: File, namePrefix: String): DigestedFile = {
    DigestedFile(new File(dir, s"${namePrefix}-${file.digest.fingerprintHex}-${file.digest.sizeBytes}.jar"), Some(file.digest))
  }
}
