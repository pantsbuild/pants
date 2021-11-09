package org.pantsbuild.backend.scala.dependency_inference

import io.circe._
import io.circe.generic.auto._
import io.circe.syntax._

import scala.meta._
import scala.meta.transversers.Traverser

import scala.collection.mutable.ArrayBuffer
import scala.collection.mutable.HashMap

case class AnImport(name: String, isWildcard: Boolean)

case class Analysis(
  providedNames: Vector[String],
  importsByScope: HashMap[String, ArrayBuffer[AnImport]],
)

class SourceAnalysisTraverser extends Traverser {
  val nameParts = ArrayBuffer[String]()

  val providedNames = ArrayBuffer[String]()
  val importsByScope = HashMap[String, ArrayBuffer[AnImport]]()

  // Extract a qualified name from a tree.
  def extractName(tree: Tree): String = {
    tree match {
      case Term.Select(qual, name) => s"${extractName(qual)}.${extractName(name)}"
      case Term.Name(name) => name
      case Type.Name(name) => name
      case Pat.Var(node) => extractName(node)
      case Name.Indeterminate(name) => name
      case _ => ""
    }
  }

  def recordProvidedName(name: String): Unit = {
    val fullPackageName = nameParts.mkString(".")
    providedNames.append(s"${fullPackageName}.${name}")
  }

  def withNamePart[T](namePart: String, f: () => T): T = {
    nameParts.append(namePart)
    val result = f()
    nameParts.remove(nameParts.length - 1)
    result
  }

  def recordImport(name: String, isWildcard: Boolean): Unit = {
    val fullPackageName = nameParts.mkString(".")
    if (!importsByScope.contains(fullPackageName)) {
      importsByScope(fullPackageName) = ArrayBuffer[AnImport]()
    }
    importsByScope(fullPackageName).append(AnImport(name, isWildcard))
  }

  override def apply(tree: Tree): Unit = tree match {
    case Pkg(ref, stats) => {
      withNamePart(extractName(ref), () => super.apply(stats))
    }

    case Defn.Class(_mods, nameNode, _tparams, _ctor, templ) => {
      val name = extractName(nameNode)
      recordProvidedName(name)
      withNamePart(name, () => super.apply(templ))
    }

    case Defn.Trait(_mods, nameNode, _tparams, _ctor, templ) => {
      val name = extractName(nameNode)
      recordProvidedName(name)
      withNamePart(name, () => super.apply(templ))
    }

    case Defn.Object(_mods, nameNode, templ) => {
      val name = extractName(nameNode)
      recordProvidedName(name)
      withNamePart(name, () => super.apply(templ))
    }

    case Defn.Type(_mods, nameNode, _tparams, _body) => {
      val name = extractName(nameNode)
      recordProvidedName(name)
    }

    case Defn.Val(_mods, pats, _decltpe, _rhs) => {
      pats.headOption.foreach(pat => {
        val name = extractName(pat)
        recordProvidedName(name)
      })
    }

    case Defn.Var(_mods, pats, _decltpe, _rhs) => {
      pats.headOption.foreach(pat => {
        val name = extractName(pat)
        recordProvidedName(name)
      })
    }

    case Import(importers) => {
      importers.foreach({ case Importer(ref, importees) =>
        val baseName = extractName(ref)
        importees.foreach(importee => {
          importee match {
            case Importee.Wildcard() => recordImport(baseName, true)
            case Importee.Name(nameNode) => recordImport(s"${baseName}.${extractName(nameNode)}", false)
            case Importee.Rename(nameNode, _) => recordImport(s"${baseName}.${extractName(nameNode)}", false)
            case _ =>
          }
        })
      })
    }

    case node => super.apply(node)
  }
}

object ScalaParser {
  def analyze(pathStr: String): Analysis = {
    val path = java.nio.file.Paths.get(pathStr)
    val bytes = java.nio.file.Files.readAllBytes(path)
    val text = new String(bytes, "UTF-8")
    val input = Input.VirtualFile(path.toString, text)

    val tree = input.parse[Source].get

    val analysisTraverser = new SourceAnalysisTraverser()
    analysisTraverser.apply(tree)

    Analysis(
      providedNames = analysisTraverser.providedNames.toVector,
      importsByScope = analysisTraverser.importsByScope,
    )
  }

  def main(args: Array[String]): Unit = {
    val outputPath = java.nio.file.Paths.get(args(0))
    val analysis = analyze(args(1))

    val json = analysis.asJson.noSpaces
    java.nio.file.Files.write(outputPath, json.getBytes(),
      java.nio.file.StandardOpenOption.CREATE_NEW, java.nio.file.StandardOpenOption.WRITE)
  }
}
