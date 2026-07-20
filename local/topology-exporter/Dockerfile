# Local image for network-topology-exporter.
# GHCR pulls require auth for some environments; build from the GitHub release binary instead:
#   make topology-exporter-image
FROM alpine:3.21
RUN apk add --no-cache ca-certificates
COPY build/topology-exporter-linux-amd64 /usr/local/bin/topology-exporter
USER nobody
ENTRYPOINT ["/usr/local/bin/topology-exporter"]
