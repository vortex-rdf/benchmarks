FROM ubuntu:20.04

ARG VIRTUOSO_VERSION=7.2.17
ARG VIRTUOSO_ARCHIVE=virtuoso-opensource.x86_64-generic_glibc25-linux-gnu.tar.gz
ARG VIRTUOSO_SHA256=45385ea8c1940e41d88d628f9318bbc992081c4cd5c4e18b57277b6df516b15b
ARG VIRTUOSO_URL=https://github.com/openlink/virtuoso-opensource/releases/download/v${VIRTUOSO_VERSION}/${VIRTUOSO_ARCHIVE}

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl libncurses5 \
 && rm -rf /var/lib/apt/lists/*
RUN curl --fail --location --retry 5 -o /tmp/${VIRTUOSO_ARCHIVE} ${VIRTUOSO_URL} \
 && echo "${VIRTUOSO_SHA256}  /tmp/${VIRTUOSO_ARCHIVE}" | sha256sum --check --strict \
 && mkdir -p /opt/virtuoso \
 && tar -xzf /tmp/${VIRTUOSO_ARCHIVE} -C /opt/virtuoso --strip-components=1 \
 && rm /tmp/${VIRTUOSO_ARCHIVE} \
 && ln -s /opt/virtuoso/bin/virtuoso-t /usr/local/bin/virtuoso-t \
 && ln -s /opt/virtuoso/bin/isql /usr/local/bin/isql \
 && ln -s /opt/virtuoso/bin/inifile /usr/local/bin/inifile \
 && mkdir -p /database /usr/share/proj
COPY entrypoint.sh /usr/local/bin/virtuoso-entrypoint.sh
RUN chmod 0755 /usr/local/bin/virtuoso-entrypoint.sh
ENV VIRTUOSO_HOME=/opt/virtuoso PATH=/opt/virtuoso/bin:${PATH} DBA_PASSWORD=root
WORKDIR /database
EXPOSE 1111 8890
ENTRYPOINT ["/usr/local/bin/virtuoso-entrypoint.sh"]
CMD ["start"]
