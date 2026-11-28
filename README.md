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

### Internal tools (never published)

| Artifact | Description | Repository |
|---|---|---|
| `secret-sync` | Pushes the deployment secrets in `qa.properties` / `prod.properties` to GitHub Actions: checks every value, shows what will change, asks for confirmation (`PROD` for production), never deletes | [smmakvana/paramichha-github-secret](https://github.com/smmakvana/paramichha-github-secret) (private) |

Internal tools take this parent for the same Java version, plugin versions and quality checks, and set
`maven.deploy.skip` and `skipPublishing` so nothing reaches Maven Central.

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
- Publishing: GitHub Packages by default (`mvn deploy`, see below); Maven Central with `-P release`

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
    </plugins>
</build>
```

## Limitations

- **Java 21 or later** — the compiler release is fixed at 21 for all libraries.
- **Lombok is managed but not scoped.** Children must declare it `provided` (or `test`) themselves, or it leaks
  to their consumers as a compile dependency.
- **Releases need a GPG key and Central Portal token** on the machine that runs `mvn deploy -P release`.

## Building on Windows and Unix

All repositories use `* text=auto eol=lf` in `.gitattributes`, and this parent configures
Spotless with `lineEndings=UNIX`. Keep these settings on both operating systems; no global Git
configuration change is needed. Pulling the attributes does not necessarily rewrite files that
were already checked out as CRLF. A Spotless diff showing `\r\n` replaced by `\n` means those
existing files need a one-time conversion.

From the folder containing the repositories, run this with Python 3 on Windows or Unix
(`python3` on Unix, or `py -3` on Windows, if that is your Python command):

```bash
python paramichha-dev/scripts/normalize-line-endings.py paramichha-dev paramichha-utils datafactory-catalog paramichha-datafactory paramichha-testkit paramichha-testbuddy
```

Use your actual directory names (for example, `paramichha-datafactory-catalog` instead of
`datafactory-catalog`) and quote paths containing spaces. The command only replaces CRLF with LF
in tracked text files governed by `eol=lf`; it preserves content edits and does not stage files,
reset the checkout, or touch untracked files. Add `--check` to report without changing files.
Then rerun your normal build. Fresh checkouts already use LF, so the command is also safe to
include after pulling and before building in an existing build script.

## Publishing to GitHub Packages (private libraries)

A library is released by publishing a **GitHub Release** in its repository, tagged `v<version>` (for
example `v0.2.0` for version `0.2.0` in `pom.xml`). Its `release.yml` calls this repository's
`.github/workflows/publish.yml`, which checks the tag matches the version (and is not a `-SNAPSHOT`),
builds and tests, and runs `mvn deploy` to `https://maven.pkg.github.com/<owner>/<repository>`.
A package there is as private as its repository.

Release in the order above (`paramichha-dev` → `paramichha-utils` → `datafactory-catalog` →
`paramichha-datafactory` → `paramichha-testkit`): each release builds the ones before it from their
default branch, so those must already hold the released versions it depends on.

**Letting another repository build with a package** (once per package, by the owner): open the package
(the repository's *Packages* section) → *Package settings* → *Manage Actions access* → *Add repository*
→ choose the repository → role *Read*. Its workflows then read the package with their own
`GITHUB_TOKEN` (`permissions: packages: read`) and a Maven `settings.xml` that lists
`https://maven.pkg.github.com/<owner>/<repository>` as a repository with server id `github`.

**On your own machine**, Maven needs a token to read the packages: create a GitHub personal access
token (classic) with only `read:packages`, and put it in `~/.m2/settings.xml` under server id `github`
(username: your GitHub login). Never commit it.

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
