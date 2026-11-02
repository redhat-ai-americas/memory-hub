# Full memory content

The dashboard loads S3-backed memories from object storage before displaying
their content, version history or branches, or proposing a promotion. The
database prefix is never treated as the complete editable document. If storage
is unavailable, these operations return HTTP 503 so the prefix cannot silently
replace the full document. Content hidden by the viewer's access policy is not
fetched from storage.

Configure the BFF with the same object storage settings used by the MCP server:

- `MEMORYHUB_S3_ENDPOINT`: MinIO host and port, without a URL scheme.
- `MEMORYHUB_S3_ACCESS_KEY` and `MEMORYHUB_S3_SECRET_KEY`: storage credentials.
- `MEMORYHUB_S3_BUCKET`: content bucket, default `memoryhub`.
- `MEMORYHUB_S3_SECURE`: whether to use TLS, default `true`.

Store credentials in the deployment's secret configuration. Restart the BFF
after changing storage settings. New versions use the configured storage
adapter when their content exceeds the core S3 threshold.
