# Patched ktranslate binary on the official runtime image (GeoIP, profiles, caps).
# Build context must be a ktranslate checkout (e.g. Mesverrum/ktranslate fix/otel-chf-flow-only).

FROM golang:1.25-alpine AS build
RUN apk add --no-cache libpcap-dev gcc musl-dev bash
WORKDIR /src
COPY . .
RUN go generate ./pkg/version \
 && CGO_ENABLED=1 go build -tags dynamic -ldflags="-s -w" -o /ktranslate ./cmd/ktranslate

FROM quay.io/kentik/ktranslate:latest
USER root
COPY --from=build /ktranslate /usr/local/bin/ktranslate
RUN setcap cap_net_raw=+ep /usr/local/bin/ktranslate 2>/dev/null || true
USER ktranslate
