# syntax=docker/dockerfile:1
# A CMaNGOS realm for the Leyline host kit ("host any client"), built on the host's own PC from its authors' source.
# The same recipe serves profiles/cmangos-1.12.1 (CMaNGOS Classic) and profiles/cmangos-2.4.3 (CMaNGOS TBC); the
# hosting tests keep the two copies identical. profiles/host-profile.sh passes every LL_* line of profile.lock:
#
#   docker build --target server     -t <LL_IMAGE>-server:<tag>     --build-arg LL_CORE_REPO=... <profile dir>
#   docker build --target extractors -t <LL_IMAGE>-extractors:<tag> ...
#   docker build --target db-import  -t <LL_IMAGE>-db-import:<tag>  ...
#
# No binaries come from Leyline: mangosd, realmd and the extractors are compiled here from the pinned commit of
# the core (GPL-2.0). The world database is the project's own SQL at the pinned commit of its database repo
# (GPL-2.0). No stage fetches game data: the extractors image only holds the tools that read the host's OWN client
# later (extract.sh). Licence texts and the exact sources stay in every image under /licenses.

ARG BASE=ubuntu:24.04

# ---------------------------------------------------------------------------------------------- the sources
FROM ${BASE} AS source
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
ARG LL_CORE_REPO
ARG LL_CORE_COMMIT
ARG LL_DB_REPO
ARG LL_DB_COMMIT
# Exactly the pinned commits, over HTTPS (refused when an argument is missing or the checkout differs).
RUN set -eu; \
    for v in "$LL_CORE_REPO" "$LL_CORE_COMMIT" "$LL_DB_REPO" "$LL_DB_COMMIT"; do [ -n "$v" ] || { echo "missing build arg (use host-profile.sh)" >&2; exit 1; }; done; \
    case "$LL_CORE_REPO $LL_DB_REPO" in *http://*) echo "HTTPS only" >&2; exit 1 ;; esac; \
    case "$LL_CORE_REPO $LL_DB_REPO" in "https://github.com/cmangos/"*" https://github.com/cmangos/"*) ;; *) echo "refused: not the CMaNGOS project" >&2; exit 1 ;; esac; \
    fetch() { mkdir -p "$2"; cd "$2"; git init -q; git remote add origin "$1"; \
              git fetch -q --depth 1 origin "$3"; git checkout -q FETCH_HEAD; \
              [ "$(git rev-parse HEAD)" = "$3" ] || { echo "$1 is not at $3" >&2; exit 1; }; rm -rf .git; }; \
    fetch "$LL_CORE_REPO" /src/core "$LL_CORE_COMMIT"; \
    fetch "$LL_DB_REPO" /src/db "$LL_DB_COMMIT"; \
    mkdir -p /licenses/core /licenses/db; \
    cp /src/core/LICENSE /src/core/COPYRIGHT.md /src/core/AUTHORS.md /licenses/core/; \
    cp /src/db/LICENSE.md /src/db/COPYRIGHT.md /licenses/db/; \
    printf 'Built from source by the Leyline host kit (profiles/<profile>/NOTICE.md).\n\nserver (GPL-2.0): %s @ %s\nworld database (GPL-2.0): %s @ %s\n' \
      "$LL_CORE_REPO" "$LL_CORE_COMMIT" "$LL_DB_REPO" "$LL_DB_COMMIT" > /licenses/SOURCES.txt

# ---------------------------------------------------------------------------------------------- the compile
FROM ${BASE} AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake ca-certificates pkg-config \
      libboost-all-dev libmariadb-dev libmariadb-dev-compat libssl-dev zlib1g-dev libbz2-dev \
 && rm -rf /var/lib/apt/lists/*
COPY --from=source /src/core /src/core
# JOBS: parallel compile jobs. Each needs about 2 GB of RAM; host-profile.sh picks min(CPUs, RAM / 2 GB).
ARG JOBS=2
# The build tree is a cache mount: an interrupted build carries on where it stopped when run again.
ARG LL_PROFILE=cmangos
RUN --mount=type=cache,target=/build,id=leyline-${LL_PROFILE}-build \
    cmake -S /src/core -B /build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/cmangos \
          -DBUILD_EXTRACTORS=ON -DBUILD_PLAYERBOTS=OFF -DBUILD_AHBOT=OFF -DBUILD_METRICS=OFF -DPCH=ON \
 && cmake --build /build -j"$JOBS" \
 && cmake --install /build \
 && strip /opt/cmangos/bin/mangosd /opt/cmangos/bin/realmd /opt/cmangos/bin/tools/ad \
          /opt/cmangos/bin/tools/vmap_extractor /opt/cmangos/bin/tools/vmap_assembler /opt/cmangos/bin/tools/MoveMapGen

# ---------------------------------------------------------------------------------------------- mangosd + realmd
FROM ${BASE} AS server
RUN apt-get update && apt-get install -y --no-install-recommends \
      libmariadb3 libssl3t64 zlib1g libbz2-1.0 ca-certificates libboost-system1.83.0 libboost-program-options1.83.0 \
      libboost-thread1.83.0 libboost-regex1.83.0 libboost-serialization1.83.0 libboost-filesystem1.83.0 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -r -u 10003 -d /opt/cmangos mangos && mkdir -p /logs && chown mangos /logs
COPY --from=build /opt/cmangos/bin/mangosd /opt/cmangos/bin/realmd /opt/cmangos/bin/
COPY --from=build /opt/cmangos/etc/ /opt/cmangos/etc/
COPY --from=source /licenses /licenses
COPY run-server.sh leyline-mangosd.conf leyline-realmd.conf /opt/leyline/
RUN chmod 755 /opt/leyline/run-server.sh \
 && ! ldd /opt/cmangos/bin/mangosd /opt/cmangos/bin/realmd | grep "not found"
USER mangos
WORKDIR /opt/cmangos
ENTRYPOINT ["/opt/leyline/run-server.sh"]
CMD ["mangosd"]

# ---------------------------------------------------------------------------------------------- the extractors
# Runs once against the host's own client folder (mounted read-only at /client); writes /data only.
FROM ${BASE} AS extractors
RUN apt-get update && apt-get install -y --no-install-recommends libssl3t64 zlib1g libbz2-1.0 libmariadb3 \
      libboost-system1.83.0 libboost-program-options1.83.0 libboost-thread1.83.0 libboost-filesystem1.83.0 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/cmangos/bin/tools/ /opt/cmangos/bin/tools/
COPY --from=source /src/core/contrib/extractor_scripts/config.json /src/core/contrib/extractor_scripts/offmesh.txt /opt/cmangos/bin/tools/
COPY --from=source /licenses /licenses
COPY extract.sh /opt/leyline/
RUN chmod 755 /opt/leyline/extract.sh \
 && ! ldd /opt/cmangos/bin/tools/ad /opt/cmangos/bin/tools/vmap_extractor /opt/cmangos/bin/tools/vmap_assembler \
          /opt/cmangos/bin/tools/MoveMapGen | grep "not found"
ENTRYPOINT ["/opt/leyline/extract.sh"]

# ---------------------------------------------------------------------------------------------- the databases
# The project's own installer (InstallFullDB.sh of the database repo) over the core's sql/ folder, both at the
# pinned commits. db-import.sh runs it without questions and never drops accounts or characters after the first run.
FROM mariadb:11.4 AS db-import
COPY --from=source /src/db /opt/db
COPY --from=source /src/core/sql /opt/core/sql
COPY --from=source /licenses /licenses
COPY db-import.sh /opt/leyline/
ARG LL_DB_COMMIT
ARG LL_BUILD
ARG LL_EXPANSION
RUN chmod 755 /opt/leyline/db-import.sh && echo "$LL_DB_COMMIT" > /opt/db/.leyline-version \
 && echo "$LL_BUILD" > /opt/db/.leyline-build && echo "$LL_EXPANSION" > /opt/db/.leyline-expansion
ENTRYPOINT ["/opt/leyline/db-import.sh"]
