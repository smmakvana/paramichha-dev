# paramichha-dev

Parent POM for all [Paramichha](https://paramichha.com) open-source developer tools.

This is a `pom`-only artifact — it contains no code. It provides shared build configuration, dependency version management, and Maven Central publishing setup that all Paramichha open-source projects inherit.

## Projects

| Artifact | Description | Version |
|---|---|---|
| [datafactory](https://github.com/paramichha/datafactory) | Generate valid and invalid test data from Jakarta-annotated POJOs | ![Maven Central](https://img.shields.io/maven-central/v/com.paramichha/datafactory) |
| [testkit](https://github.com/paramichha/testkit) | Code generation toolkit for Jakarta Bean Validation aware test scaffolding | ![Maven Central](https://img.shields.io/maven-central/v/com.paramichha/testkit) |

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

## Publishing to Maven Central

Normal development — no signing, builds locally:

```bash
mvn clean install
```

Snapshot — publishes to OSSRH snapshot repository:

```bash
mvn deploy
```

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

## License

[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)
