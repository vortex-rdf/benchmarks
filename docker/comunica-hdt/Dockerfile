ARG NODE_VERSION=24.19.0
FROM node:${NODE_VERSION}-bookworm-slim AS build
ARG COMUNICA_HDT_VERSION=5.0.1
WORKDIR /opt/comunica-hdt
RUN apt-get update \
 && apt-get install --yes --no-install-recommends python3 make g++ \
 && rm -rf /var/lib/apt/lists/*
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts=false --no-audit --no-fund \
 && test "$(node -p "require('./node_modules/@comunica/query-sparql-hdt/package.json').version")" = "$COMUNICA_HDT_VERSION" \
 && npm cache clean --force

FROM node:${NODE_VERSION}-bookworm-slim AS runtime
ARG COMUNICA_HDT_VERSION=5.0.1
WORKDIR /opt/comunica-hdt
COPY --from=build --chown=node:node /opt/comunica-hdt/package.json /opt/comunica-hdt/package-lock.json ./
COPY --from=build --chown=node:node /opt/comunica-hdt/node_modules ./node_modules
RUN test "$(node -p "require('./node_modules/@comunica/query-sparql-hdt/package.json').version")" = "$COMUNICA_HDT_VERSION" \
 && test -x ./node_modules/.bin/comunica-sparql-hdt-http
USER node
ENTRYPOINT ["/opt/comunica-hdt/node_modules/.bin/comunica-sparql-hdt-http"]
# Usage: docker run -p 3000:3000 -v /path/dataset.hdt:/data/dataset.hdt:ro <image> hdt@/data/dataset.hdt -p 3000 -w 1 -t 10
# (Comunica's own SPARQL endpoint; the paper's embedded worker used the same engine and HDT source type.)
EXPOSE 3000
