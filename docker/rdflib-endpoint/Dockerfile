# One SPARQL HTTP server for every rdflib-based system under test: Vortex-RDF (vortex-rdflib),
# RDFLib, COTTAS (pycottas) and optimized HDT (rdflib-hdt). Only the store differs between them;
# the HTTP layer, query parsing and result serialization are identical.
#
#   docker build -t vortex-rdf-bench/rdflib-endpoint:vrl-0.1.3 \
#       --build-arg VORTEX_RDFLIB_VERSION=0.1.3 --build-arg VORTEX_RDF_VERSION=0.10.0 docker/rdflib-endpoint
#
# vortex-rdflib 0.1.x needs vortex-rdf 0.10.x; vortex-rdflib 0.2.x needs vortex-rdf 0.11.x; vortex-rdflib 0.3.x needs vortex-rdf
# 0.12.1+, whose store format v2 refuses stores written by vortex-rdf 0.11 or earlier.
ARG PYTHON_IMAGE=python:3.13-slim-bookworm
FROM ${PYTHON_IMAGE}

# rdflib-hdt "3.3" is the upstream repository state below (not on PyPI); it needs a compiler.
ARG RDFLIB_HDT_COMMIT=58b82c27a5a0a1c5db833dd9fb1fd63b3a22c783
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG RDFLIB_VERSION=7.6.0
ARG RDFLIB_ENDPOINT_VERSION=0.6.3
ARG PYCOTTAS_VERSION=1.1.0
ARG VORTEX_RDF_VERSION=0.10.0
ARG VORTEX_RDFLIB_VERSION=0.1.3
RUN pip install --no-cache-dir \
      "rdflib==${RDFLIB_VERSION}" "rdflib-endpoint==${RDFLIB_ENDPOINT_VERSION}" "uvicorn[standard]" \
      "pycottas==${PYCOTTAS_VERSION}" "vortex-rdf==${VORTEX_RDF_VERSION}" "vortex-rdflib==${VORTEX_RDFLIB_VERSION}" \
      pybind11 setuptools wheel \
 && pip install --no-cache-dir --no-build-isolation \
      "git+https://github.com/RDFLib/rdflib-hdt.git@${RDFLIB_HDT_COMMIT}"

COPY serve_rdflib.py /app/serve_rdflib.py
WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["python", "/app/serve_rdflib.py"]
