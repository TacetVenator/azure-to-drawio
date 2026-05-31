#!/usr/bin/env bash
set -euo pipefail

# Azure Keyword Search and Export
# Searches for resources matching a keyword in:
#   - Resource Group names
#   - Tag values
#   - Tag keys
# Outputs results to CSV with columns: ResourceId, Name, ResourceGroup, Tags, Region

KEYWORD="${1:-ERP}"
OUT_FILE="${2:-azure-keyword-search-${KEYWORD}.csv}"
SUB_ID="${SUBSCRIPTION_ID:-}"

command -v az >/dev/null || { echo "Missing az CLI"; exit 1; }
command -v jq >/dev/null || { echo "Missing jq"; exit 1; }

az extension add --name resource-graph --only-show-errors 2>/dev/null || true

# If no subscription provided, get current default
if [[ -z "$SUB_ID" ]]; then
  SUB_ID=$(az account show -o json | jq -r '.id')
fi

echo "Searching for resources matching keyword: '$KEYWORD'" >&2
echo "Subscription: $SUB_ID" >&2
echo "Output file: $OUT_FILE" >&2

# Build the KQL query
# This searches for:
# 1. Resources where resourceGroup contains the keyword
# 2. Resources where any tag value contains the keyword
# 3. Resources where any tag key contains the keyword
read -r -d '' QUERY << 'EOF' || true
resources
| union (
    resources
    | where isnotempty(tags)
    | mvexpand tags
    | extend tagkey = tostring(bag_keys(tags)[0])
    | extend tagValue = tostring(tags[tagkey])
    | where tagValue contains "SEARCH_KEYWORD" or tagkey contains "SEARCH_KEYWORD"
)
| where resourceGroup contains "SEARCH_KEYWORD" or isnotempty(tags)
| extend TagsJson = tostring(tags)
| distinct id, name, resourceGroup, TagsJson, location
| project ResourceId = id, Name = name, ResourceGroup = resourceGroup, Tags = TagsJson, Region = location
EOF

# Replace placeholder with actual keyword
QUERY="${QUERY//SEARCH_KEYWORD/$KEYWORD}"

echo "Executing query..." >&2

# Execute query and export to CSV
json=$(az graph query \
  --subscriptions "$SUB_ID" \
  --first 5000 \
  -q "$QUERY" \
  -o json)

# Convert JSON to CSV
if echo "$json" | jq -e '.data | length > 0' >/dev/null 2>&1; then
  echo "$json" | jq -r '
    .data
    | (.[0] | keys_unsorted) as $keys
    | ($keys | @csv), (.[] | [.[$keys[]] // ""] | @csv)
  ' > "$OUT_FILE"
  
  result_count=$(echo "$json" | jq '.data | length')
  echo "✓ Found $result_count resources matching keyword '$KEYWORD'" >&2
  echo "✓ Results exported to: $OUT_FILE" >&2
else
  echo "⚠ No resources found matching keyword '$KEYWORD'" >&2
  exit 0
fi

# Display summary
echo "" >&2
echo "=== Search Results Summary ===" >&2
echo "Keyword: $KEYWORD" >&2
echo "Total Resources: $result_count" >&2
echo "" >&2
echo "Resource Groups found:" >&2
jq -r '.data[].ResourceGroup' "$OUT_FILE" | sort -u | sed 's/^/  - /' >&2

exit 0
