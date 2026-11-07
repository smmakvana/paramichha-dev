# paramichha-dev

[![Java 21+](https://img.shields.io/badge/Java-21%2B-blue)](https://openjdk.org/) [![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-green)](LICENSE)

The parent POM for the Paramichha libraries. It pins Java 21, shared plugin and dependency versions, and the Maven Central release configuration, so each library's POM stays short.

## Projects

| Artifact | Description | Repository |
|---|---|---|
| `paramichha-utils` | Dependency-free utilities: deterministic seeds, naming, type inspection, guards | [smmakvana/paramichha-utils](https://github.com/smmakvana/paramichha-utils) |
| `datafactory` | Generate valid and invalid test data from Jakarta-annotated classes | [smmakvana/paramichha-datafactory](https://github.com/smmakvana/paramichha-datafactory) |
| `datafactory-catalog` | Jakarta-annotated test fixtures (records, Lombok, all-args, JavaBeans) | [smmakvana/datafactory-catalog](https://github.com/smmakvana/datafactory-catalog) |
| `testkit` | Generate JUnit 5 tests from Jakarta Bean Validation annotations | [smmakvana/paramichha-testkit](https://github.com/smmakvana/paramichha-testkit) |
| `paramichha-bom` | One version for all the libraries above: import it, then add them without versions | [smmakvana/paramichha-bom](https://github.com/smmakvana/paramichha-bom) |

All use `groupId` `com.paramichha`.

### Dependency and release order

```
paramichha-dev  →  paramichha-utils  →  datafactory-catalog  →  datafactory  →  testkit  →  paramichha-bom
```

Release in this order: each project needs the one before it to be resolvable, and Maven Central rejects a
release that depends on a `-SNAPSHOT` (including a `-SNAPSHOT` parent).

## Using this parent

Add to your `pom.xml`:

```xml
<parent>
    <groupId>com.paramichha</groupId>
    <artifactId>paramichha-dev</artifactId>
    <version>1.0.0</version>
</parent>
```

Your project inherits:
- Java 21 compiler configuration with Lombok annotation processing
- Dependency version management for Jakarta Validation, Hibernate Validator, DataFaker, Lombok, JUnit 5, AssertJ
- Source and Javadoc jar generation
- GPG signing (activated via `-P release`)
- Maven Central publishing via `central-publishing-maven-plugin`

## What to declare in your child pom

Dependencies — groupId and artifactId only, no versions:

```xml
<dependencies>
    <dependency>
        <groupId>jakarta.validation</groupId>
        <artifactId>jakarta.validation-api</artifactId>
    </dependency>
    <dependency>
        <groupId>org.junit.jupiter</groupId>
        <artifactId>junit-jupiter</artifactId>
    </dependency>
</dependencies>
```

Plugins — groupId and artifactId only, no versions, no configuration:

```xml
<build>
    <plugins>
        <plugin>
            <groupId>org.apache.maven.plugins</groupId>
            <artifactId>maven-compiler-plugin</artifactId>
        </plugin>
        <plugin>
            <groupId>org.sonatype.central</groupId>
            <artifactId>central-publishing-maven-plugin</artifactId>
        </plugin>
    </plugins>
</build>
```

## Limitations

- **Java 21 or later** — the compiler release is fixed at 21 for all libraries.
- **Lombok is managed but not scoped.** Children must declare it `provided` (or `test`) themselves, or it leaks
  to their consumers as a compile dependency.
- **Releases need a GPG key and Central Portal token** on the machine that runs `mvn deploy -P release`.

## Publishing to Maven Central

### Release everything at once

`scripts/release-all.sh` releases all six artifacts in dependency order, the BOM last with the library
versions it has just released. Run it from the folder that holds
all the repositories:

```bash
bash paramichha-dev/scripts/release-all.sh --dry-run   # build with release versions; changes nothing
bash paramichha-dev/scripts/release-all.sh             # deploy, commit, tag vX, bump to next SNAPSHOT, push
```

The versions to release are at the top of the script. It refuses to continue if any repository has uncommitted
changes or if a `SNAPSHOT` would be left in a pom. `--dry-run` uses a separate local Maven repository
(`.release-dry-run-m2`), so `~/.m2` isn't touched.

### Releasing one project by hand

Normal development — no signing, builds locally:

```bash
mvn clean install
```

Snapshots are not deployed anywhere. `mvn install` puts a `-SNAPSHOT` build in your local `~/.m2`, which is
how the projects in this family use each other during development. Releases go to Maven Central (below).

Release — signs artifacts and publishes to Maven Central:

```bash
mvn versions:set -DnewVersion=1.0.0
mvn deploy -P release
git tag v1.0.0 && git push --tags
mvn versions:set -DnewVersion=1.1.0-SNAPSHOT
git commit -am "prepare next development iteration"
git push
```

Requires GPG key configured and `~/.m2/settings.xml`:

```xml
<settings>
    <servers>
        <server>
            <id>central</id>
            <username>YOUR_CENTRAL_TOKEN_USERNAME</username>
            <password>YOUR_CENTRAL_TOKEN_PASSWORD</password>
        </server>
    </servers>
</settings>
```

## Managed dependency versions

| Dependency | Version property |
|---|---|
| `jakarta.validation-api` | `${jakarta.validation.version}` |
| `hibernate-validator` | `${hibernate.validator.version}` |
| `expressly` | `${expressly.version}` |
| `datafaker` | `${datafaker.version}` |
| `lombok` | `${lombok.version}` |
| `junit-jupiter` | `${junit.version}` |
| `assertj-core` | `${assertj.version}` |

To override a version in a child project, redeclare the property:

```xml
<properties>
    <junit.version>5.11.0</junit.version>
</properties>
```

## Contributing

Open an issue to discuss a change, then send a pull request. Run `mvn -q install -DskipTests` to check that the parent builds.

## License

[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)
