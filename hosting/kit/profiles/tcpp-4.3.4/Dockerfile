# syntax=docker/dockerfile:1
# A 4.3.4 realm on TrinityCore (The Cataclysm Preservation Project's 4.3.4 fork) for the Leyline host kit ("host any
# client"), built on the host's own PC from its authors' source. profiles/host-profile.sh passes the LL_* lines of
# profile.lock:
#
#   docker build --target server     -t leyline-tcpp-434-server:<tag>     --build-arg LL_CORE_REPO=... <profile dir>
#   docker build --target extractors -t leyline-tcpp-434-extractors:<tag> ...
#   docker build --target db-import  -t leyline-tcpp-434-db-import:<tag>  ...
#
# No binaries come from Leyline: worldserver, authserver and the extractors are compiled here from the pinned commit
# (GPL-2.0). The world database is the project's TDB release file, checked against its sha256 in profile.lock. No
# stage fetches game data: the extractors image only holds the tools that read the host's OWN 4.3.4 client later
# (extract.sh). Licence texts and the exact sources stay in every image under /licenses.

ARG BASE=ubuntu:24.04

# ---------------------------------------------------------------------------------------------- the sources
FROM ${BASE} AS source
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
ARG LL_CORE_REPO
ARG LL_CORE_COMMIT
RUN set -eu; \
    for v in "$LL_CORE_REPO" "$LL_CORE_COMMIT"; do [ -n "$v" ] || { echo "missing build arg (use host-profile.sh)" >&2; exit 1; }; done; \
    case "$LL_CORE_REPO" in https://github.com/The-Cataclysm-Preservation-Project/*) ;; *) echo "refused: $LL_CORE_REPO" >&2; exit 1 ;; esac; \
    mkdir -p /src/core; cd /src/core; git init -q; git remote add origin "$LL_CORE_REPO"; \
    git fetch -q --depth 1 origin "$LL_CORE_COMMIT"; git checkout -q FETCH_HEAD; \
    [ "$(git rev-parse HEAD)" = "$LL_CORE_COMMIT" ] || { echo "not at $LL_CORE_COMMIT" >&2; exit 1; }; rm -rf .git; \
    mkdir -p /licenses/core; cp /src/core/COPYING /src/core/AUTHORS /licenses/core/; \
    printf 'Built from source by the Leyline host kit (profiles/tcpp-4.3.4/NOTICE.md).\n\nserver (GPL-2.0): %s @ %s\n' \
      "$LL_CORE_REPO" "$LL_CORE_COMMIT" > /licenses/SOURCES.txt

# ---------------------------------------------------------------------------------------------- the compile
FROM ${BASE} AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake ca-certificates pkg-config \
      libboost-all-dev default-libmysqlclient-dev libssl-dev zlib1g-dev libbz2-dev libreadline-dev libncurses-dev \
 && rm -rf /var/lib/apt/lists/*
COPY --from=source /src/core /src/core
ARG JOBS=2
RUN --mount=type=cache,target=/build,id=leyline-tcpp-434-build \
    cmake -S /src/core -B /build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/tc \
          -DSERVERS=1 -DTOOLS=1 -DSCRIPTS=static -DWITH_WARNINGS=0 -DWITH_COREDEBUG=0 -DWITHOUT_GIT=1 \
          -DUSE_COREPCH=1 -DUSE_SCRIPTPCH=1 -DBUILD_TESTING=0 \
 && cmake --build /build -j"$JOBS" \
 && cmake --install /build \
 && strip /opt/tc/bin/worldserver /opt/tc/bin/authserver /opt/tc/bin/mapextractor /opt/tc/bin/vmap4extractor \
          /opt/tc/bin/vmap4assembler /opt/tc/bin/mmaps_generator

# ---------------------------------------------------------------------------------------------- worldserver + authserver
FROM ${BASE} AS server
RUN apt-get update && apt-get install -y --no-install-recommends \
      libmysqlclient21 libssl3t64 zlib1g libbz2-1.0 libreadline8t64 ca-certificates \
      libboost-system1.83.0 libboost-program-options1.83.0 libboost-thread1.83.0 libboost-regex1.83.0 \
      libboost-filesystem1.83.0 libboost-iostreams1.83.0 libboost-locale1.83.0 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -r -u 10004 -d /opt/tc trinity && mkdir -p /logs && chown trinity /logs
COPY --from=build /opt/tc/bin/worldserver /opt/tc/bin/authserver /opt/tc/bin/
COPY --from=build /opt/tc/etc/ /opt/tc/etc/
COPY --from=source /licenses /licenses
COPY run-server.sh leyline-worldserver.conf leyline-authserver.conf /opt/leyline/
RUN chmod 755 /opt/leyline/run-server.sh \
 && ! ldd /opt/tc/bin/worldserver /opt/tc/bin/authserver | grep "not found"
USER trinity
WORKDIR /opt/tc
ENTRYPOINT ["/opt/leyline/run-server.sh"]
CMD ["worldserver"]

# ---------------------------------------------------------------------------------------------- the extractors
FROM ${BASE} AS extractors
RUN apt-get update && apt-get install -y --no-install-recommends libssl3t64 zlib1g libbz2-1.0 libmysqlclient21 \
      libboost-system1.83.0 libboost-program-options1.83.0 libboost-thread1.83.0 libboost-filesystem1.83.0 \
      libboost-iostreams1.83.0 libboost-locale1.83.0 libboost-regex1.83.0 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/tc/bin/mapextractor /opt/tc/bin/vmap4extractor /opt/tc/bin/vmap4assembler /opt/tc/bin/mmaps_generator /opt/tc/bin/
COPY --from=source /licenses /licenses
COPY extract.sh /opt/leyline/
RUN chmod 755 /opt/leyline/extract.sh \
 && ! ldd /opt/tc/bin/mapextractor /opt/tc/bin/vmap4extractor /opt/tc/bin/vmap4assembler /opt/tc/bin/mmaps_generator | grep "not found"
ENTRYPOINT ["/opt/leyline/extract.sh"]

# ---------------------------------------------------------------------------------------------- the databases
FROM ${BASE} AS sql
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates p7zip-full \
 && rm -rf /var/lib/apt/lists/*
ARG LL_DB_URL
ARG LL_DB_SHA256
ARG LL_DB_FILES
# The project's own TDB release only (no game data in it), checked against the sha256 in profile.lock.
RUN set -eu; \
    case "$LL_DB_URL" in https://github.com/The-Cataclysm-Preservation-Project/TrinityCore/releases/download/*) ;; *) echo "refused: $LL_DB_URL" >&2; exit 1 ;; esac; \
    echo "$LL_DB_SHA256" | grep -Eq '^[0-9a-f]{64}$' || { echo "profile.lock has no sha256 for the database file yet (TODO(owner))" >&2; exit 1; }; \
    curl -fsSL --proto '=https' -o /tmp/tdb.7z "$LL_DB_URL"; echo "$LL_DB_SHA256  /tmp/tdb.7z" | sha256sum -c -; \
    mkdir -p /db; cd /db; 7z e -y -bd /tmp/tdb.7z '*.sql' >/dev/null; rm -f /tmp/tdb.7z; \
    for f in $(echo "$LL_DB_FILES" | tr ',' ' '); do [ -s "/db/$f" ] || { echo "no $f in the release file" >&2; exit 1; }; done

# The import: the world server's own updater (--update-databases-only, Updates.AutoSetup) makes the four databases
# from sql/base and the TDB files, then applies sql/updates of the pinned commit. Safe on every start.
FROM server AS db-import
USER root
RUN apt-get update && apt-get install -y --no-install-recommends mariadb-client && rm -rf /var/lib/apt/lists/*
COPY --from=source /src/core/sql /opt/tc/src/sql
COPY --from=sql /db /opt/tc/db
RUN chown -R trinity /opt/tc/db
USER trinity
WORKDIR /opt/tc/db
CMD ["update"]
