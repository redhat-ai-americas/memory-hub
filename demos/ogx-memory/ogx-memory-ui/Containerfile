FROM registry.redhat.io/ubi9/go-toolset:1.22 AS builder

WORKDIR /opt/app-root/src
COPY go.mod ./
COPY cmd/ cmd/
COPY static/ static/

RUN go build -o ./ui-server ./cmd/server

FROM registry.redhat.io/ubi9/ubi-minimal:latest

LABEL io.opencontainers.image.title="ui-template" \
      io.opencontainers.image.description="Chat UI for AI agents"

COPY --from=builder /opt/app-root/src/ui-server /ui-server

USER 1001
EXPOSE 3000

CMD ["/ui-server"]
