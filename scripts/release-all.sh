#!/usr/bin/env bash
#
# Release every Paramichha artifact to Maven Central, in dependency order:
#
#   paramichha-dev -> paramichha-utils -> datafactory-catalog -> datafactory -> testkit
#
# Run from the folder that contains all the repositories:
#
#   bash paramichha-dev/scripts/release-all.sh --dry-run    # build with release versions, change nothing
#   bash paramichha-dev/scripts/release-all.sh              # deploy, commit, tag, bump, push
#
# For each repository it: checks it is clean and up to date on master, sets the release version,
# points the parent and the other paramichha dependencies at their release versions, refuses to go
# on if any SNAPSHOT is left in the pom (Maven Central rejects those), builds and deploys with
# -P release (signed), then commits "Release X", tags vX, sets the next -SNAPSHOT version and pushes.
#
# --dry-run builds with the release versions into a separate local Maven repository (so ~/.m2 is
# not touched), then restores the poms. Nothing is deployed, committed, tagged or pushed.
#
# Real releases need a GPG key (gpg --list-secret-keys) and a Central Portal token in
# ~/.m2/settings.xml under <server><id>central</id>. Check the versions below first.

set -euo pipefail

# ── Versions to release ──────────────────────────────────────────────────────
DEV_VERSION=1.1.0
UTILS_VERSION=0.1.0
CATALOG_VERSION=0.2.0
DATAFACTORY_VERSION=0.2.0
TESTKIT_VERSION=0.2.0
BOM_VERSION=1.0.0        # paramichha-bom: released last, lists the versions above

# ── Next development versions, set after each release ────────────────────────
DEV_NEXT=1.2.0-SNAPSHOT
UTILS_NEXT=0.2.0-SNAPSHOT
CATALOG_NEXT=0.3.0-SNAPSHOT
DATAFACTORY_NEXT=0.3.0-SNAPSHOT
TESTKIT_NEXT=0.3.0-SNAPSHOT
BOM_NEXT=1.1.0-SNAPSHOT

BRANCH=${BRANCH:-master}   # override for testing: BRANCH=my-branch bash release-all.sh --dry-run
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

ROOT="$(pwd)"
MVN=(mvn -B)
if $DRY_RUN; then
    MVN+=("-Dmaven.repo.local=$ROOT/.release-dry-run-m2")
    echo ">>> DRY RUN — nothing will be deployed, committed, tagged or pushed"
fi

say()  { echo; echo "==================== $* ===================="; }
fail() { echo "!! $*" >&2; exit 1; }

# Folder for a repository; accepts either the GitHub name or a local alias.
dir_for() {
    for d in "$@"; do [[ -d "$ROOT/$d/.git" ]] && { echo "$ROOT/$d"; return; }; done
    fail "none of these folders found in $ROOT: $*"
}

DEV_DIR=$(dir_for paramichha-dev)
UTILS_DIR=$(dir_for paramichha-utils)
CATALOG_DIR=$(dir_for datafactory-catalog paramichha-datafactory-catalog)
DATAFACTORY_DIR=$(dir_for paramichha-datafactory)
TESTKIT_DIR=$(dir_for paramichha-testkit)
BOM_DIR=$(dir_for paramichha-bom)

# ── Preflight ────────────────────────────────────────────────────────────────
if ! $DRY_RUN; then
    command -v gpg >/dev/null || fail "gpg not found — needed to sign artifacts"
    [[ -n "$(gpg --list-secret-keys 2>/dev/null)" ]] || fail "no GPG secret key — create one and publish it to a keyserver"
    grep -q "<id>central</id>" "$HOME/.m2/settings.xml" 2>/dev/null \
        || fail "~/.m2/settings.xml has no <server><id>central</id> with your Central Portal token"
fi

# Never release a version that exists on Central or is lower than the latest one there.
CENTRAL=https://repo.maven.apache.org/maven2/com/paramichha
check_central() {
    local artifact=$1 version=$2 meta latest code tmp
    tmp=$(mktemp)
    for attempt in 1 2 3; do
        code=$(curl -s -o "$tmp" -w '%{http_code}' "$CENTRAL/$artifact/maven-metadata.xml" || true)
        [[ "$code" == 200 || "$code" == 404 ]] && break
        sleep $((attempt * 5))   # 429 rate limit or network error: retry
    done
    meta=$(cat "$tmp"); rm -f "$tmp"
    if [[ "$code" == 404 ]]; then
        echo "   $artifact $version: not on Central yet"
        return
    fi
    # Only a real 404 means "never published"; anything else must not be guessed.
    [[ "$code" == 200 ]] || fail "could not check $artifact on Maven Central (HTTP $code) — try again later"
    if grep -q "<version>$version</version>" <<<"$meta"; then
        fail "$artifact $version is already on Maven Central — choose a higher version"
    fi
    latest=$(grep -oE "<version>[^<]+</version>" <<<"$meta" | sed -E 's#</?version>##g' | sort -V | tail -1)
    if [[ "$(printf '%s\n%s\n' "$latest" "$version" | sort -V | tail -1)" != "$version" ]]; then
        fail "$artifact $version is lower than $latest on Maven Central — choose a higher version"
    fi
    echo "   $artifact $version: higher than $latest on Central"
}
say "versions vs Maven Central"
command -v curl >/dev/null || fail "curl not found — needed to check versions on Maven Central"
check_central paramichha-dev      "$DEV_VERSION"
check_central paramichha-utils    "$UTILS_VERSION"
check_central datafactory-catalog "$CATALOG_VERSION"
check_central datafactory         "$DATAFACTORY_VERSION"
check_central testkit             "$TESTKIT_VERSION"
check_central paramichha-bom      "$BOM_VERSION"

for d in "$DEV_DIR" "$UTILS_DIR" "$CATALOG_DIR" "$DATAFACTORY_DIR" "$TESTKIT_DIR" "$BOM_DIR"; do
    ( cd "$d"
      [[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail "$(basename "$d") has uncommitted changes"
      git checkout -q "$BRANCH"
      git pull -q --ff-only ) || exit 1
done

# ── Pom editing ──────────────────────────────────────────────────────────────

# Point <parent> paramichha-dev and every paramichha dependency/property at release versions.
pin_versions() {
    perl -0pi -e '
        s#(<parent>\s*<groupId>com\.paramichha</groupId>\s*<artifactId>paramichha-dev</artifactId>\s*<version>)[^<]+#${1}'"$DEV_VERSION"'#;
        s#(<artifactId>paramichha-utils</artifactId>\s*<version>)[^<\$]+#${1}'"$UTILS_VERSION"'#g;
        s#(<artifactId>datafactory-catalog</artifactId>\s*<version>)[^<\$]+#${1}'"$CATALOG_VERSION"'#g;
        s#(<artifactId>datafactory</artifactId>\s*<version>)[^<\$]+#${1}'"$DATAFACTORY_VERSION"'#g;
        s#(<artifactId>testkit</artifactId>\s*<version>)[^<\$]+#${1}'"$TESTKIT_VERSION"'#g;
        s#(<paramichha-utils\.version>)[^<]+#${1}'"$UTILS_VERSION"'#g;
        s#(<datafactory-catalog\.version>)[^<]+#${1}'"$CATALOG_VERSION"'#g;
        s#(<datafactory\.version>)[^<]+#${1}'"$DATAFACTORY_VERSION"'#g;
        s#(<testkit\.version>)[^<]+#${1}'"$TESTKIT_VERSION"'#g;
        s#(<paramichha-quality-rules\.version>)[^<]+#${1}'"$DEV_VERSION"'#g;
    ' pom.xml
}

release_repo() {
    local dir=$1 version=$2 next=$3 name
    name=$(basename "$dir")
    say "$name $version"
    cd "$dir"

    pin_versions   # first: versions:set below has to resolve the (released) parent
    "${MVN[@]}" -q versions:set -DnewVersion="$version" -DgenerateBackupPoms=false -DprocessAllModules=true
    if grep -n "SNAPSHOT" pom.xml; then
        git checkout -q -- pom.xml
        fail "$name: SNAPSHOT left in pom.xml (above) — Maven Central would reject the release"
    fi

    if $DRY_RUN; then
        "${MVN[@]}" clean install -P release -Dgpg.skip=true \
            | grep -E "Tests run:.*Fail.*Skipped: [0-9]+$|BUILD|ERROR\]" | tail -3
        # install the artifact so the next repository can resolve it, then restore the pom
        git checkout -q -- pom.xml
        echo "   dry run OK: $name would be released as $version"
    else
        "${MVN[@]}" clean deploy -P release \
            | grep -E "Tests run:.*Fail.*Skipped: [0-9]+$|BUILD|ERROR\]|Deployment|published" | tail -5
        git commit -q -am "Release $version"
        git tag -a "v$version" -m "Release $version"
        "${MVN[@]}" -q versions:set -DnewVersion="$next" -DgenerateBackupPoms=false -DprocessAllModules=true
        git commit -q -am "Prepare next development iteration $next"
        git push -q origin "$BRANCH" "v$version"
        echo "   released $name $version, master is now $next"
    fi
    cd "$ROOT"
}

set -o pipefail
release_repo "$DEV_DIR"         "$DEV_VERSION"         "$DEV_NEXT"
release_repo "$UTILS_DIR"       "$UTILS_VERSION"       "$UTILS_NEXT"
release_repo "$CATALOG_DIR"     "$CATALOG_VERSION"     "$CATALOG_NEXT"
release_repo "$DATAFACTORY_DIR" "$DATAFACTORY_VERSION" "$DATAFACTORY_NEXT"
release_repo "$TESTKIT_DIR"     "$TESTKIT_VERSION"     "$TESTKIT_NEXT"
release_repo "$BOM_DIR"         "$BOM_VERSION"         "$BOM_NEXT"   # last: lists the versions released above

say "done"
if $DRY_RUN; then
    echo "Dry run complete. Every repository builds with release versions and no SNAPSHOTs."
    echo "Remove $ROOT/.release-dry-run-m2 when finished."
else
    echo "Released. Artifacts appear on https://central.sonatype.com within minutes;"
    echo "repo1.maven.org can take up to a few hours."
fi
