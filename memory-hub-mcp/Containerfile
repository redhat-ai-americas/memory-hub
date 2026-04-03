FROM registry.redhat.io/ubi9/python-311:latest

WORKDIR /opt/app-root/src

# Install dependencies with pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code with proper permissions for OpenShift
COPY --chown=1001:0 src/ ./src/

# FIX: Claude Code's Write tool creates files with 600 permissions (owner-only).
# OpenShift containers run as arbitrary non-root UIDs that need read access.
# This ensures all Python files are readable (644) regardless of source permissions.
# See: https://docs.openshift.com/container-platform/4.14/openshift_images/create-images.html#use-uid_create-images
RUN find ./src -name "*.py" -exec chmod 644 {} \;

# Set environment for HTTP transport
ENV MCP_TRANSPORT=http \
    MCP_HTTP_HOST=0.0.0.0 \
    MCP_HTTP_PORT=8080 \
    MCP_HTTP_PATH=/mcp/

USER 1001

# Run the application
CMD ["python", "-m", "src.main"]