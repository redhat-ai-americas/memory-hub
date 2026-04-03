#!/usr/bin/env bash
# Validates that PostgreSQL with pgvector is correctly deployed and functional.
# Usage: ./scripts/validate-postgresql.sh [namespace]
set -euo pipefail

NAMESPACE="${1:-memoryhub-db}"
POD_LABEL="app.kubernetes.io/name=memoryhub-pg"
DB_USER="memoryhub"
DB_NAME="memoryhub"

passed=0
failed=0

run_sql() {
  oc exec -n "$NAMESPACE" statefulset/memoryhub-pg -- \
    psql -U "$DB_USER" -d "$DB_NAME" -tAc "$1" 2>&1
}

check() {
  local description="$1"
  local sql="$2"
  local expected="$3"

  printf "  %-50s " "$description"
  result=$(run_sql "$sql") || { echo "FAIL (exec error)"; ((failed++)); return; }

  if echo "$result" | grep -qi "$expected"; then
    echo "OK"
    ((passed++))
  else
    echo "FAIL (got: $result)"
    ((failed++))
  fi
}

echo "=== MemoryHub PostgreSQL Validation ==="
echo "Namespace: $NAMESPACE"
echo ""

# Check pod is running
printf "  %-50s " "Pod is running"
if oc get pod -n "$NAMESPACE" -l "$POD_LABEL" -o jsonpath='{.items[0].status.phase}' 2>/dev/null | grep -q "Running"; then
  echo "OK"
  ((passed++))
else
  echo "FAIL (pod not running)"
  echo "Aborting: PostgreSQL pod is not running."
  exit 1
fi

# Check extensions
echo ""
echo "--- Extension checks ---"
check "pgvector extension is installed" \
  "SELECT extname FROM pg_extension WHERE extname = 'vector';" \
  "vector"

check "uuid-ossp extension is installed" \
  "SELECT extname FROM pg_extension WHERE extname = 'uuid-ossp';" \
  "uuid-ossp"

# Functional test with vectors
echo ""
echo "--- Functional vector test ---"

printf "  %-50s " "Create test table with vector column"
run_sql "CREATE TABLE IF NOT EXISTS _validate_test (id serial PRIMARY KEY, embedding vector(3));" >/dev/null 2>&1 \
  && { echo "OK"; ((passed++)); } \
  || { echo "FAIL"; ((failed++)); }

printf "  %-50s " "Insert test vectors"
run_sql "
  INSERT INTO _validate_test (embedding) VALUES
    ('[1,0,0]'),
    ('[0,1,0]'),
    ('[0,0,1]'),
    ('[0.9,0.1,0]');
" >/dev/null 2>&1 \
  && { echo "OK"; ((passed++)); } \
  || { echo "FAIL"; ((failed++)); }

check "Cosine similarity search returns results" \
  "SELECT count(*) FROM _validate_test ORDER BY embedding <=> '[1,0,0]' LIMIT 2;" \
  "4"

check "Nearest neighbor is correct (cosine)" \
  "SELECT embedding::text FROM _validate_test ORDER BY embedding <=> '[1,0,0]' LIMIT 1;" \
  "\[1,0,0\]"

# Clean up
printf "  %-50s " "Clean up test table"
run_sql "DROP TABLE IF EXISTS _validate_test;" >/dev/null 2>&1 \
  && { echo "OK"; ((passed++)); } \
  || { echo "FAIL"; ((failed++)); }

# Summary
echo ""
echo "=== Results: $passed passed, $failed failed ==="

if [ "$failed" -gt 0 ]; then
  exit 1
fi
