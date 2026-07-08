# Stage 1: Build
FROM registry.redhat.io/ubi9/go-toolset:1.22 AS builder

WORKDIR /opt/app-root/src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd/ cmd/
COPY internal/ internal/
RUN go build -o ./gateway ./cmd/server

# Stage 2: Runtime
FROM registry.redhat.io/ubi9/ubi-minimal:latest

LABEL io.opencontainers.image.title="gateway-template" \
      io.opencontainers.image.version="0.1.0" \
      io.opencontainers.image.description="OpenAI-compatible HTTP gateway for AI agents" \
      io.opencontainers.image.vendor="Red Hat AI Americas"

COPY --from=builder /opt/app-root/src/gateway /gateway

USER 1001
EXPOSE 8080

CMD ["/gateway"]
