Pants for Maven Experts
=======================

If you're used to Maven and learning Pants, you're part of a growing
crowd. Here are some things that helped other folks come up to speed.

The good news is that Pants and Maven are pretty similar. Both tools use
several configuration-snippet files near in source code directories to
specify how to build those directories' source code. Both tools use the
configuration-snippet files to build up a model of your source code,
then execute tasks in a lifecycle over that model. Pants targets tend to
be finer-grained than Maven's projects; but if you use subprojects in
Maven, Pants targets might feel familiar. (If you're converting Maven
`pom.xml`s to `BUILD` files, <a pantsref="setup_mvn2pants">some scripts written by others who
have done the same</a> can give you a head start.)
Both Maven and Pants expect code to be laid out in directories in a consistent way. If you're used
to Maven's commands, many of Pants' goals will feel familiar.

Pants uses Ivy to manage artifact fetching and publishing; Ivy's
behavior here is pretty similar to Maven.

Three Pants features that especially confuse Maven experts as they move
to pants are:

-   Pants has a first-class mechanism for targets depending on other
    targets on the local file system
-   Pants targets do not specify version numbers; versions are only
    determined during release

These points are a significant departure from Maven's handling
of inter-project dependencies.

Folks switching a Maven-built codebase to Pants often encounter another
source of confusion: they uncover lurking jar-dependency version
conflicts. JVM projects can inadvertently end up relying on classpath
order for correctness; any two build tools will order their classpaths
differently. If your project depends on two versions of the same jar
(all too easy to do with transitive dependencies), then your Maven build
chose one version, but Pants might end up choosing another: Pants is
likely to generate a differently-ordered `CLASSPATH` than Maven did. You
can fix these, making your build configuration more robust along the
way; see
[[JVM 3rdparty Pattern|pants('examples/src/java/org/pantsbuild/example:3rdparty_jvm')]]
for advice.

Pants Equivalents
-----------------

### Commands

**Run a binary**<br>
Maven: `exec:java`<br>
Pants: `run`

**Run a binary in the debugger**<br>
Maven: `-Xdebug`<br>
Pants: `run.jvm --jvm-debug`

**Run one test in the debugger**<br>
Maven: `-Dtest=com.foo.BarSpec -Dmaven.surefire.debug=true test`<br>
Pants: `test.junit --jvm-debug --test=com.foo.BarSpec`

**Build a binary package**<br>
Maven: `package`<br>
Pants: `binary`<br>

**Look at dependent projects or artifacts**<br>
Maven: `dependency:analyze`<br>
Pants: `depmap`<br>
Pants: `resolve.ivy --open`<br>

### Configuration

**Shade with an AppendingTransformer**<br>

Maven
```xml
<plugins>
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-shade-plugin</artifactId>
    <executions>
        <execution>
            <goals>
                <goal>shade</goal>
            </goals>
            <configuration>
                <transformers>
                    <transformer implementation="org.apache.maven.plugins.shade.resource.AppendingTransformer">
                        <resource>reference.conf</resource>
                    </transformer>
                </transformers>
            </configuration>
        </execution>
    </executions>
</plugin>
</plugins>
```

Pants
```python
jvm_binary(name='your-bin',
           main = 'pkg.to.my.Main',
           deploy_jar_rules=jar_rules(rules=[
              Duplicate('^reference\.conf', Duplicate.CONCAT_TEXT),

              # We need to add this as it is overridden by adding the reference.conf one above.
              Duplicate('^META-INF/services/', Duplicate.CONCAT_TEXT)
          ]))
```

**Dependency Scopes**<br>

Pants supports dependency scopes. To emulate Maven's `provided` scope you
can specify both the `compile` and `test` scopes for a target. For details,
see [[JVM Projects with Pants|pants('examples/src/java/org/pantsbuild/example:readme')]].

Maven
```xml
<dependency>
  <groupId>org.apache.spark</groupId>
  <artifactId>spark-core_2.11</artifactId>
  <scope>provided</scope>
</dependency>
```

Pants
```python
jar_library(
  name='spark-core',
  jars=[
    scala_jar(org='org.apache.spark', name='spark-core', rev='2.1.0'),
  ],
  scope='compile test',
)
```
