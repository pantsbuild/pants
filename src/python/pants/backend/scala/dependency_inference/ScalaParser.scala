package org.pantsbuild.backend.scala.dependency_inference

import io.circe._, io.circe.generic.auto._, io.circe.syntax._
//import io.circe._
//import io.circe.generic.auto._
//import io.circe.syntax._

import scala.meta._

case class Analysis(
  `package`: String
)

object ScalaParser {
  def analyze(pathStr: String): Analysis = {
    val path = java.nio.file.Paths.get(pathStr)
    val bytes = java.nio.file.Files.readAllBytes(path)
    val text = new String(bytes, "UTF-8")
    val input = Input.VirtualFile(path.toString, text)

    val tree = input.parse[Source].get

    // TODO: Actually pare out the package (and other fields).
    Analysis("foo")
  }

  def main(args: Array[String]): Unit = {
    val analysis = analyze(args(0))

    val json = analysis.asJson.noSpaces
    // TODO: Write to file specified by the caler.
    println(json)
  }
}
