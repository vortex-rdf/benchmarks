ARG QLEVER_IMAGE=adfreiburg/qlever@sha256:37d5ede193f1bffb6aebf734d15d2a4c2a3228ee102858b0c6c2e65c149a78ec
FROM ${QLEVER_IMAGE}

LABEL org.vortex-rdf-bench.system="qlever/default"       org.vortex-rdf-bench.qlever.version="0.6.0"       org.vortex-rdf-bench.upstream.digest="sha256:37d5ede193f1bffb6aebf734d15d2a4c2a3228ee102858b0c6c2e65c149a78ec"

# The upstream entrypoint requires the container working directory to be /data.
WORKDIR /data
