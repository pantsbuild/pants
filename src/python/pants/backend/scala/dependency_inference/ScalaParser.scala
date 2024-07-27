/** TODO: The dependencies of this class are defined in two places:
  *   1. `3rdparty/jvm` via import inference. 2. `SCALA_PARSER_ARTIFACT_REQUIREMENTS`. See
  *      https://github.com/pantsbuild/pants/issues/13754.
  */
package org.pantsbuild.backend.scala.dependency_inference

import cats.data.{Chain, NonEmptyChain}
import cats.syntax.all._

import io.circe._
import io.circe.generic.auto._
import io.circe.syntax._

import scala.meta._
import scala.meta.transversers.Traverser
import scala.meta.Stat.{WithMods, WithCtor, WithTemplate}
import scala.meta.Tree.WithTParamClause

import scala.collection.SortedSet
import scala.collection.mutable.{ArrayBuffer, HashMap, HashSet}
import scala.reflect.NameTransformer

object Constants {
  // `_root_` is used in Scala as a marker for absolute qualified names
  // https://docs.scala-lang.org/tour/packages-and-imports.html#imports
  val RootPackageQualifier = "_root_"

  val NameSeparator = '.'
}

case class QualifiedName(private val parts: NonEmptyChain[String]) {
  def isAbsolute: Boolean = parts.head == Constants.RootPackageQualifier

  def elements: Chain[String] =
    if (isAbsolute) parts.tail
    else parts.toChain

  def parents: Chain[String] = {
    elements.initLast.map(_._1).getOrElse(Chain.empty)
  }

  def simpleName: Option[String] = {
    elements.lastOption
  }

  lazy val fullName: String =
    elements.intercalate(Constants.NameSeparator.toString)

  def qualify(name: String): QualifiedName =
    QualifiedName.fromString(name).map(qualify(_)).getOrElse(this)

  def qualify(other: QualifiedName): QualifiedName =
    if (other.isAbsolute) other
    else QualifiedName(parts ++ other.parts)

}
object QualifiedName {
  val Root = QualifiedName(NonEmptyChain.one(Constants.RootPackageQualifier))

  def of(name: String): QualifiedName =
    QualifiedName(NonEmptyChain.one(name))

  def fromString(str: String): Option[QualifiedName] = {
    // This split shouldn't be necessary, it's just a fail-safe
    val parts = str.split(Constants.NameSeparator)
    NonEmptyChain.fromSeq(parts).map(QualifiedName(_))
  }

}

case class AnImport[A](
    // The partially qualified input name for the import, which must be in scope at
    // the import site.
    name: A,
    // An optional single token alias for the import in this scope.
    alias: Option[String],
    // True if the import imports all symbols contained within the name.
    isWildcard: Boolean
) {
  def map[B](f: A => B): AnImport[B] =
    copy(name = f(name))
}

case class Analysis(
    providedSymbols: SortedSet[Analysis.ProvidedSymbol],
    providedSymbolsEncoded: SortedSet[Analysis.ProvidedSymbol],
    importsByScope: Map[String, List[AnImport[String]]],
    consumedSymbolsByScope: Map[String, SortedSet[Analysis.ConsumedSymbol]],
    scopes: Vector[String]
)
object Analysis {
  case class ProvidedSymbol(name: String, recursive: Boolean)
  case class ConsumedSymbol(name: String, isAbsolute: Boolean)

  implicit val providedSymbolOrdering: Ordering[ProvidedSymbol] = Ordering.by(_.name)
  implicit val consumedSymbolOrdering: Ordering[ConsumedSymbol] = Ordering.by(_.name)
}

case class ProvidedSymbol(
    sawObject: Boolean,
    recursive: Boolean
)

class SourceAnalysisTraverser extends Traverser {
  val nameParts = ArrayBuffer[String](Constants.RootPackageQualifier)
  var skipProvidedNames = false

  val providedSymbolsByScope = HashMap[QualifiedName, HashMap[String, ProvidedSymbol]]()
  val importsByScope = HashMap[QualifiedName, ArrayBuffer[AnImport[QualifiedName]]]()
  val consumedSymbolsByScope = HashMap[QualifiedName, HashSet[QualifiedName]]()
  val scopes = HashSet[QualifiedName]()

  def currentScope: QualifiedName = {
    // We know `nameParts` is always non-empty, so we can be unsafe here
    QualifiedName(NonEmptyChain.fromChainUnsafe(Chain.fromSeq(nameParts.toVector)))
  }

  // Extract a qualified name from a tree.
  def extractName(tree: Tree): Option[QualifiedName] = {
    def extractNameSelect(qual: Tree, name: Tree): Option[QualifiedName] =
      (maybeExtractName(qual), maybeExtractName(name)) match {
        case (Some(qual), Some(name)) => Some(qual.qualify(name))
        case (Some(qual), None)       => Some(qual)
        case (None, Some(name))       => Some(name)
        case (None, None)             => None
      }

    def maybeExtractName(tree: Tree): Option[QualifiedName] =
      tree match {
        case Term.Select(qual, name)  => extractNameSelect(qual, name)
        case Type.Select(qual, name)  => extractNameSelect(qual, name)
        case Term.Name(name)          => QualifiedName.fromString(name)
        case Type.Name(name)          => QualifiedName.fromString(name)
        case Pat.Var(node)            => maybeExtractName(node)
        case Name.Indeterminate(name) => QualifiedName.fromString(name)
        case _                        => None
      }

    maybeExtractName(tree)
  }

  def extractNamesFromTypeTree(tree: Tree): Chain[QualifiedName] = {
    tree match {
      case Type.Name(name) => Chain.one(QualifiedName.of(name))
      case Type.Select(qual, Type.Name(name)) => {
        val symbol = extractName(qual).map(_.qualify(name)).getOrElse(QualifiedName.of(name))
        Chain.one(symbol)
      }
      case Type.Apply(tpe, args) =>
        extractNamesFromTypeTree(tpe) ++ Chain.fromSeq(args).flatMap(extractNamesFromTypeTree(_))
      case Type.ApplyInfix(lhs, _op, rhs) =>
        extractNamesFromTypeTree(lhs) ++ extractNamesFromTypeTree(rhs)
      case Type.Function(params, res) =>
        Chain.fromSeq(params).flatMap(extractNamesFromTypeTree(_)) ++ extractNamesFromTypeTree(res)
      case Type.PolyFunction(_tparams, tpe) => extractNamesFromTypeTree(tpe)
      case Type.ContextFunction(params, res) =>
        Chain.fromSeq(params).flatMap(extractNamesFromTypeTree(_)) ++ extractNamesFromTypeTree(res)
      case Type.Tuple(args)    => Chain.fromSeq(args).flatMap(extractNamesFromTypeTree(_))
      case Type.With(lhs, rhs) => extractNamesFromTypeTree(lhs) ++ extractNamesFromTypeTree(rhs)
      case Type.And(lhs, rhs)  => extractNamesFromTypeTree(lhs) ++ extractNamesFromTypeTree(rhs)
      case Type.Or(lhs, rhs)   => extractNamesFromTypeTree(lhs) ++ extractNamesFromTypeTree(rhs)
      // TODO: Recurse into `_stats` to find additional types.
      // A `Type.Refine` represents syntax: A { def f: Int }
      case Type.Refine(typeOpt, _stats)  => Chain.fromOption(typeOpt).flatMap(extractNamesFromTypeTree(_))
      case Type.Existential(tpe, _stats) => extractNamesFromTypeTree(tpe)
      case Type.Annotate(tpe, _annots)   => extractNamesFromTypeTree(tpe)
      case Type.Lambda(_tparams, tpe)    => extractNamesFromTypeTree(tpe)
      case Type.Bounds(loOpt, hiOpt) =>
        Chain.fromOption(loOpt).flatMap(extractNamesFromTypeTree(_)) ++ Chain.fromOption(hiOpt).flatMap(extractNamesFromTypeTree(_))
      case Type.ByName(tpe)   => extractNamesFromTypeTree(tpe)
      case Type.Repeated(tpe) => extractNamesFromTypeTree(tpe)
      // TODO: Should we extract a type from _tpe?
      // `Type.Match` represents this Scala 3 syntax: type T = match { case A => B }
      case Type.Match(_tpe, cases) => Chain.fromSeq(cases).flatMap(extractNamesFromTypeTree(_))
      case TypeCase(pat, body) => extractNamesFromTypeTree(pat) ++ extractNamesFromTypeTree(body)
      case _                   => Chain.empty
    }
  }

  def recordProvidedName(
      symbolQName: QualifiedName,
      sawObject: Boolean = false,
      recursive: Boolean = false
  ): Unit = {
    if (!skipProvidedNames) {
      val fullPackageName = currentScope
      if (!providedSymbolsByScope.contains(fullPackageName)) {
        providedSymbolsByScope(fullPackageName) = HashMap[String, ProvidedSymbol]()
      }
      val providedSymbols = providedSymbolsByScope(fullPackageName)

      val symbolName = symbolQName.fullName
      if (providedSymbols.contains(symbolName)) {
        val existingSymbol = providedSymbols(symbolName)
        val newSymbol = ProvidedSymbol(
          sawObject = existingSymbol.sawObject || sawObject,
          recursive = existingSymbol.recursive || recursive
        )
        providedSymbols(symbolName) = newSymbol
      } else {
        providedSymbols(symbolName) = ProvidedSymbol(
          sawObject = sawObject,
          recursive = recursive
        )
      }
    }
  }

  def withNamePart[T](namePart: String, f: () => T): T = {
    nameParts.append(namePart)
    val result = f()
    nameParts.remove(nameParts.length - 1)
    result
  }

  def withSuppressProvidedNames[T](f: () => T): Unit = {
    val origSkipProvidedNames = skipProvidedNames
    skipProvidedNames = true
    f()
    skipProvidedNames = origSkipProvidedNames
  }

  def recordImport(name: QualifiedName, alias: Option[String], isWildcard: Boolean): Unit = {
    val fullPackageName = currentScope
    if (!importsByScope.contains(fullPackageName)) {
      importsByScope(fullPackageName) = ArrayBuffer[AnImport[QualifiedName]]()
    }
    importsByScope(fullPackageName).append(AnImport(name, alias, isWildcard))
  }

  def recordConsumedSymbol(name: QualifiedName): Unit = {
    val fullPackageName = currentScope
    if (!consumedSymbolsByScope.contains(fullPackageName)) {
      consumedSymbolsByScope(fullPackageName) = HashSet[QualifiedName]()
    }
    consumedSymbolsByScope(fullPackageName).add(name)
  }

  def recordScope(name: String): Unit = {
    QualifiedName.fromString(name).foreach(recordScope(_))
  }

  def recordScope(name: QualifiedName): Unit = {
    scopes.add(currentScope.qualify(name))
  }

  def visitTemplate(templ: Template, name: String): Unit = {
    templ.inits.foreach(init => apply(init))
    withNamePart(
      name,
      () => {
        apply(templ.self)
        apply(templ.early)
        apply(templ.stats)
      }
    )
  }

  def visitMods(mods: List[Mod]): Unit = {
    mods.foreach({
      case Mod.Annot(init) =>
        apply(init) // rely on `Init` extraction in main parsing match code
      case _ => ()
    })
  }

  override def apply(tree: Tree): Unit = tree match {
    case Pkg(ref, stats) => {
      extractName(ref).foreach { qname =>
        recordScope(qname)
        qname.parents.iterator.foreach(nameParts.append(_))
        qname.simpleName.foreach { name =>
          withNamePart(name, () => super.apply(stats))
        }    
      }
    }

    case Pkg.Object(mods, nameNode, templ) => {
      visitMods(mods)
      extractName(nameNode).foreach { qname =>
        recordScope(qname)

        // TODO: should object already be recursive?
        // an object is recursive if extends another type because we cannot figure out the provided types
        // in the parents, we just mark the object as recursive (which is indicated by non-empty inits)
        val recursive = !templ.inits.isEmpty
        recordProvidedName(qname, sawObject = true, recursive = recursive)

        // visitTemplate visits the inits part of the template in the outer scope,
        // however for a package object the inits part can actually be found both in the inner scope as well (package inner).
        // therefore we are not calling visitTemplate, calling all the apply methods in the inner scope.
        // issue https://github.com/pantsbuild/pants/issues/16259
        qname.simpleName.foreach { name =>
          withNamePart(
            name,
            () => {
              templ.inits.foreach(init => apply(init))
              apply(templ.early)
              apply(templ.stats)
            }
          )
        }
      }
    }

    case defn: Member.Type with WithMods with WithTParamClause with WithCtor with WithTemplate => // traits, enums and classes
      visitMods(defn.mods)
      extractName(defn.name).foreach { name =>
        recordProvidedName(name)
        apply(defn.tparamClause)
        apply(defn.ctor)
        name.simpleName.foreach(visitTemplate(defn.templ, _))        
      }

    case Defn.EnumCase.After_4_6_0(mods, nameNode, tparamClause, ctor, _) =>
      visitMods(mods)
      extractName(nameNode).foreach { name =>
        recordProvidedName(name)
        apply(tparamClause)
        apply(ctor)
      }

    case Defn.Object(mods, nameNode, templ) => {
      visitMods(mods)
      extractName(nameNode).foreach { name =>
        // TODO: should object already be recursive?
        // an object is recursive if extends another type because we cannot figure out the provided types
        // in the parents, we just mark the object as recursive (which is indicated by non-empty inits)
        val recursive = !templ.inits.isEmpty
        recordProvidedName(name, sawObject = true, recursive = recursive)

        name.simpleName.foreach { templateName =>
          // If the object is recursive, no need to provide the symbols inside
          if (recursive)
            withSuppressProvidedNames(() => visitTemplate(templ, templateName))
          else
            visitTemplate(templ, templateName)
        }        
      }
    }

    case Defn.Type(mods, nameNode, _tparams, body) => {
      visitMods(mods)
      extractName(nameNode).foreach { name =>
        recordProvidedName(name)
        extractNamesFromTypeTree(body).iterator.foreach(recordConsumedSymbol(_))
      }
    }

    case Defn.Val(mods, pats, decltpe, rhs) => {
      visitMods(mods)
      pats.headOption.foreach(pat => {
        extractName(pat).foreach(recordProvidedName(_))
      })
      decltpe.foreach(tpe => {
        extractNamesFromTypeTree(tpe).iterator.foreach(recordConsumedSymbol(_))
      })
      super.apply(rhs)
    }

    case Defn.Var(mods, pats, decltpe, rhs) => {
      visitMods(mods)
      pats.headOption.foreach(pat => {
        extractName(pat).foreach(recordProvidedName(_))
      })
      decltpe.foreach(tpe => {
        extractNamesFromTypeTree(tpe).iterator.foreach(recordConsumedSymbol(_))
      })
      super.apply(rhs)
    }

    case Defn.Def(mods, nameNode, tparams, params, decltpe, body) => {
      visitMods(mods)
      extractName(nameNode).foreach(recordProvidedName(_))

      decltpe.foreach(tpe => {
        extractNamesFromTypeTree(tpe).iterator.foreach(recordConsumedSymbol(_))
      })

      apply(tparams)
      params.foreach(param => apply(param))

      withSuppressProvidedNames(() => apply(body))
    }

    case Decl.Def(mods, _nameNode, tparams, params, decltpe) => {
      visitMods(mods)
      extractNamesFromTypeTree(decltpe).iterator.foreach(recordConsumedSymbol(_))
      apply(tparams)
      params.foreach(param => apply(param))
    }

    case Decl.Val(mods, _pats, decltpe) => {
      visitMods(mods)
      extractNamesFromTypeTree(decltpe).iterator.foreach(recordConsumedSymbol(_))
    }

    case Decl.Var(mods, _pats, decltpe) => {
      visitMods(mods)
      extractNamesFromTypeTree(decltpe).iterator.foreach(recordConsumedSymbol(_))
    }

    case Import(importers) => {
      importers.foreach({ case Importer(ref, importees) =>
        // Importers will always have a named ref
        val baseName = extractName(ref).getOrElse(QualifiedName.Root)
        importees.foreach(importee => {
          importee match {
            case Importee.Wildcard() => recordImport(baseName, None, true)
            case Importee.Name(nameNode) => {
              extractName(nameNode).foreach { name =>
                recordImport(baseName.qualify(name), None, false)
              }
            }
            case Importee.Rename(nameNode, aliasNode) => {
              extractName(nameNode).foreach { name =>
                // If a type is aliased to `_`, it is not brought into scope. We still record
                // the import though, since compilation will fail if an import is not present.
                val alias = extractName(aliasNode).map(_.fullName).filterNot(_ == "_")
                recordImport(baseName.qualify(name), alias, false)
              }
            }
            case _ =>
          }
        })
      })
    }

    case Init(tpe, _name, argss) => {
      extractNamesFromTypeTree(tpe).iterator.foreach(recordConsumedSymbol(_))
      argss.foreach(_.foreach(apply))
    }

    case Term.Param(mods, _name, decltpe, _default) => {
      visitMods(mods)
      decltpe.foreach(tpe => {
        extractNamesFromTypeTree(tpe).iterator.foreach(recordConsumedSymbol(_))
      })
    }

    case Type.Param(mods, _name, _tparams, bounds, _vbounds, cbounds) => {
      visitMods(mods)
      extractNamesFromTypeTree(bounds).iterator.foreach(recordConsumedSymbol(_))
      Chain.fromSeq(cbounds).flatMap(extractNamesFromTypeTree(_)).iterator.foreach(recordConsumedSymbol(_))
    }

    case Ctor.Primary(mods, _name, params_list) => {
      visitMods(mods)
      params_list.foreach(params => {
        params.foreach(param => apply(param))
      })
    }

    case Ctor.Secondary(mods, _name, params_list, init, stats) => {
      visitMods(mods)
      params_list.foreach(params => {
        params.foreach(param => apply(param))
      })
      init.argss.foreach(arg => apply(arg))
    }

    case Self(_name, Some(decltpe)) =>
      extractNamesFromTypeTree(decltpe).iterator.foreach(recordConsumedSymbol(_))

    case node @ Term.Select(_, _) => {
      extractName(node).foreach(recordConsumedSymbol(_))
      apply(node.qual)
    }

    case node @ Term.Name(_) => {
      extractName(node).foreach(recordConsumedSymbol(_))
    }

    case Pat.Typed((_name, decltpe)) =>
      extractNamesFromTypeTree(decltpe).iterator.foreach(recordConsumedSymbol(_))

    case node => super.apply(node)
  }

  def gatherProvidedSymbols(): SortedSet[Analysis.ProvidedSymbol] = {
    providedSymbolsByScope
      .flatMap({ case (scopeName, symbolsForScope) =>
        symbolsForScope.map { case (symbolName, symbol) =>
          Analysis.ProvidedSymbol(scopeName.qualify(symbolName).fullName, symbol.recursive)
        }.toVector
      })
      .to(SortedSet)
  }

  def gatherEncodedProvidedSymbols(): SortedSet[Analysis.ProvidedSymbol] = {
    providedSymbolsByScope
      .flatMap({ case (scopeName, symbolsForScope) =>
        val encodedSymbolsForScope = symbolsForScope.flatMap({
          case (symbolName, symbol) => {
            val encodedSymbolName = NameTransformer.encode(symbolName)
            val result = ArrayBuffer[Analysis.ProvidedSymbol](
              Analysis.ProvidedSymbol(encodedSymbolName, symbol.recursive)
            )
            if (symbol.sawObject) {
              result.append(Analysis.ProvidedSymbol(encodedSymbolName + "$", symbol.recursive))
              result.append(
                Analysis.ProvidedSymbol(encodedSymbolName + "$.MODULE$", symbol.recursive)
              )
            }
            result.toVector
          }
        })

        encodedSymbolsForScope.map(symbol => symbol.copy(name = scopeName.qualify(symbol.name).fullName))
      })
      .to(SortedSet)
  }

  def gatherImportsByScope(): Map[String, List[AnImport[String]]] =
    importsByScope.toMap.map { case (scopeName, imports) =>
      scopeName.fullName -> imports.toList.map(_.map(_.fullName))
    }

  def gatherConsumerSymbolsByScope(): Map[String, SortedSet[Analysis.ConsumedSymbol]] = {
    consumedSymbolsByScope.toMap.map { case (scopeName, consumedSymbolNames) =>
      scopeName.fullName -> consumedSymbolNames.map(qname => Analysis.ConsumedSymbol(qname.fullName, qname.isAbsolute)).to(SortedSet)
    }
  }

  def toAnalysis: Analysis = {
    Analysis(
      providedSymbols = gatherProvidedSymbols(),
      providedSymbolsEncoded = gatherEncodedProvidedSymbols(),
      importsByScope = gatherImportsByScope(),
      consumedSymbolsByScope = gatherConsumerSymbolsByScope(),
      scopes = scopes.map(_.fullName).toVector
    )
  }
}

object ScalaParser {
  def analyze(pathStr: String, scalaVersion: String, source3: Boolean): Analysis = {
    val path = java.nio.file.Paths.get(pathStr)
    val bytes = java.nio.file.Files.readAllBytes(path)
    val text = new String(bytes, "UTF-8")

    val dialect =
      scalaVersion.take(4) match {
        case "2.10"            => dialects.Scala210
        case "2.11"            => dialects.Scala211
        case "2.12" if source3 => dialects.Scala212Source3
        case "2.12"            => dialects.Scala212
        case "2.13" if source3 => dialects.Scala213Source3
        case "2.13"            => dialects.Scala213
        case "3.0"             => dialects.Scala3
        case _ =>
          if (scalaVersion.take(2) == "3.") dialects.Scala3
          else dialects.Scala213
      }

    val input = dialect(Input.VirtualFile(path.toString, text))

    val tree = input.parse[Source].get

    val analysisTraverser = new SourceAnalysisTraverser()
    analysisTraverser.apply(tree)
    analysisTraverser.toAnalysis
  }

  def main(args: Array[String]): Unit = {
    val outputPath = java.nio.file.Paths.get(args(0))
    val pathStr = args(1)
    val scalaVersion = args(2)
    val source3 = args(3).toBoolean
    val analysis = analyze(pathStr, scalaVersion, source3)

    val json = analysis.asJson.noSpaces
    java.nio.file.Files.write(
      outputPath,
      json.getBytes(),
      java.nio.file.StandardOpenOption.CREATE_NEW,
      java.nio.file.StandardOpenOption.WRITE
    )
  }
}
