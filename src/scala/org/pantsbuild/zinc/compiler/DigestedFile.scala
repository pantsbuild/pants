package org.pantsbuild.zinc.compiler

import com.google.common.hash.HashCode
import java.io.File
import java.nio.file.{Files, Path}
import java.security.MessageDigest
import org.pantsbuild.zinc.util.Util

case class Digest(fingerprintHex: String, sizeBytes: Long)

case class DigestedFile(file: File, private val _digest: Option[Digest] = None) extends scopt.Read[DigestedFile] {

  lazy val digest = _digest.getOrElse { DigestedFile.digest(file.toPath) }

  override def arity: Int = 1

  override def reads: String => DigestedFile = DigestedFile.fromString

  def normalise(relativeTo: File): DigestedFile = {
    DigestedFile(Util.normalise(Some(relativeTo))(file), _digest)
  }
}

object DigestedFile {
  def digest(path: Path): Digest = {
    val digest = MessageDigest.getInstance("SHA-256")
    val bytes = Files.readAllBytes(path)
    Digest(HashCode.fromBytes(digest.digest(bytes)).toString, bytes.size)
  }

  def fromString(s: String): DigestedFile = {
    s.split("=", 2) match {
      case arr if arr.size == 1 => {
        val file = new File(arr(0))
        DigestedFile(file, None)
      }
      case arr if arr.size == 2 => {
        val file = new File(arr(0))
        val digest = arr(1).split("-", 2) match {
          case digestParts if digestParts.size == 2 => Digest(digestParts(0), digestParts(1).toLong)
          case _ => throw new RuntimeException(s"Bad digest: ${arr(1)}")
        }
        DigestedFile(file, Some(digest))
      }
    }
  }

  implicit def digestedFileRead: scopt.Read[DigestedFile] = scopt.Read.stringRead.map { DigestedFile.fromString }

}
