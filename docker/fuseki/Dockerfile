# Apache Jena Fuseki 6.2.0, checksum-pinned. The CDN is fast but drops old releases; archive.apache.org keeps all.
FROM eclipse-temurin:21-jre-jammy

ARG JENA_VERSION=6.2.0
ARG FUSEKI_SHA512=ba65f5867d2d4741b2ed9e2af5a0d4fbb447909894ab2a0c6bc4dac8997f4fe339c87b13c48d45d054977769f0f8bf763ea346b1f7792d5cdc458041bd43a132
ARG FUSEKI_ARCHIVE=apache-jena-fuseki-${JENA_VERSION}.tar.gz
ARG FUSEKI_URL=https://dlcdn.apache.org/jena/binaries/${FUSEKI_ARCHIVE}
ARG FUSEKI_FALLBACK_URL=https://archive.apache.org/dist/jena/binaries/${FUSEKI_ARCHIVE}

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /fuseki /fuseki/databases /fuseki/logs \
 && ( curl --fail --location --retry 3 --retry-all-errors --output /tmp/${FUSEKI_ARCHIVE} ${FUSEKI_URL} \
      || curl --fail --location --retry 5 --retry-all-errors --output /tmp/${FUSEKI_ARCHIVE} ${FUSEKI_FALLBACK_URL} ) \
 && echo "${FUSEKI_SHA512}  /tmp/${FUSEKI_ARCHIVE}" | sha512sum --check --strict \
 && tar --extract --gzip --file /tmp/${FUSEKI_ARCHIVE} \
      --directory /fuseki --strip-components=1 \
 && rm /tmp/${FUSEKI_ARCHIVE}

COPY entrypoint.sh /fuseki/entrypoint.sh
COPY log4j2.properties /fuseki/log4j2.properties

RUN useradd --system --home-dir /fuseki --shell /usr/sbin/nologin fuseki \
 && chown -R fuseki:fuseki /fuseki \
 && chmod 0755 /fuseki/entrypoint.sh /fuseki/fuseki-server

ENV FUSEKI_DIR=/fuseki \
    FUSEKI_BASE=/fuseki \
    JENA_VERSION=${JENA_VERSION} \
    JAVA_OPTIONS="-Xmx2048m -Xms2048m"

WORKDIR /fuseki
USER fuseki
EXPOSE 3030
ENTRYPOINT ["/fuseki/entrypoint.sh"]
CMD []
