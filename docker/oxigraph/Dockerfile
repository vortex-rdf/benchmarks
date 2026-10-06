FROM rust:1.96.1-bookworm AS builder
ARG OXIGRAPH_VERSION=0.5.9
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        clang cmake libclang-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*
RUN cargo install --locked --version "${OXIGRAPH_VERSION}" oxigraph-cli

FROM debian:bookworm-slim
ARG OXIGRAPH_VERSION=0.5.9
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/cargo/bin/oxigraph /usr/local/bin/oxigraph
RUN oxigraph --version | grep -F "${OXIGRAPH_VERSION}"
WORKDIR /data
EXPOSE 7878
ENTRYPOINT ["oxigraph"]
CMD ["serve", "--bind", "0.0.0.0:7878"]
