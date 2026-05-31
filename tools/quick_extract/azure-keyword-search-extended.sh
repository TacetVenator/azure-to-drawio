#!/usr/bin/env bash
set -euo pipefail

# Azure Keyword Search and Export (EXTENDED)
# Searches for resources matching a keyword in:
#   - Resource Group names
#   - Tag values
#   - Tag keys
# Exports extended details including: creation date, modification date, SKU, identity, zones, provisioning state, etc.
# Handles pagination for large result sets (tested with 6000+ resources)

KEYWORD="${1:-ERP}"
OUT_FILE="${2:-azure-keyword-search-extended-${KEYWORD}.csv}"
SUB_ID="${SUBSCRIPTION_ID:-}"
PAGE_SIZE="${PAGE_SIZE:-1000}"

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
echo "Page size: $PAGE_SIZE" >&2

# Build the KQL query with extended properties
# Searches for:
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
| extend
    createdDate = coalesce(
        todatetime(properties.creationDate),
        todatetime(properties.created),
        todatetime(properties.createdtime),
        todatetime(properties.createdTime),
        todatetime(properties.timeCreated),
        todatetime(properties.createdat),
        todatetime(properties.createdAt)
    ),
    lastModifiedDate = coalesce(
        todatetime(properties.lastModifiedDate),
        todatetime(properties.lastModifiedAt),
        todatetime(properties.lastModifiedTime),
        todatetime(properties.lastModified),
        todatetime(properties.modifiedAt),
        todatetime(properties.modifiedtime)
    ),
    provisioningState = tostring(properties.provisioningState),
    skuName = tostring(sku.name),
    skuTier = tostring(sku.tier),
    skuCapacity = tostring(sku.capacity),
    identityType = tostring(identity.type),
    identityPrincipalId = tostring(identity.principalId),
    identityTenantId = tostring(identity.tenantId),
    Zones = tostring(zones),
    tagJson = tostring(tags)
| distinct id, name, type, location, resourceGroup, tenantId, managedBy, kind,
    skuName, skuTier, skuCapacity,
    identityType, identityPrincipalId, identityTenantId,
    createdDate, lastModifiedDate, provisioningState, Zones, tagJson
| project
    ResourceId = id,
    Name = name,
    Type = type,
    ResourceGroup = resourceGroup,
    Region = location,
    TenantId = tenantId,
    ManagedBy = managedBy,
    Kind = kind,
    SkuName = skuName,
    SkuTier = skuTier,
    SkuCapacity = skuCapacity,
    IdentityType = identityType,
    IdentityPrincipalId = identityPrincipalId,
    IdentityTenantId = identityTenantId,
    CreatedDate = createdDate,
    LastModifiedDate = lastModifiedDate,
    ProvisioningState = provisioningState,
    Zones = Zones,
    Tags = tagJson
EOF

# Replace placeholder with actual keyword
QUERY="${QUERY//SEARCH_KEYWORD/$KEYWORD}"

echo "Executing query with pagination..." >&2
echo "" >&2

# Function to convert JSON to CSV
json_to_csv() {
  jq -r '
    if (.data | length) == 0 then
      empty
    else
      .data
      | (.[0] | keys_unsorted) as $keys
      | $keys, (.[] | [.[$keys[]] // ""])
      | @csv
    end
  '
}

# Function to append JSON data to CSV (without header)
json_append_csv() {
  jq -r '
    if (.data | length) == 0 then
      empty
    else
      .data
      | (.[0] | keys_unsorted) as $keys
      | .[] | [.[$keys[]] // ""]
      | @csv
    end
  '
}

# Paginate through results
skip=0
first_page=true
total_count=0

while true; do
  echo "  Fetching page at offset $skip..." >&2
  
  json=$(az graph query \
    --subscriptions "$SUB_ID" \
    --first "$PAGE_SIZE" \
    --skip "$skip" \
    -q "$QUERY" \
    -o json)
  
  count=$(echo "$json" | jq '.data | length')
  
  if [[ $count -eq 0 ]]; then
    echo "  No more results." >&2
    break
  fi
  
  if [[ "$first_page" == true ]]; then
    echo "$json" | json_to_csv > "$OUT_FILE"
    first_page=false
  else
    echo "$json" | json_append_csv >> "$OUT_FILE"
  fi
  
  total_count=$((total_count + count))
  echo "  Processed $count resources (total: $total_count)" >&2
  
  # If we got fewer results than the page size, we're done
  [[ $count -lt $PAGE_SIZE ]] && break
  
  skip=$((skip + PAGE_SIZE))
done

if [[ $total_count -gt 0 ]]; then
  echo "" >&2
  echo "✓ Found $total_count resources matching keyword '$KEYWORD'" >&2
  echo "✓ Results exported to: $OUT_FILE" >&2
  echo "" >&2
  echo "=== Search Results Summary ===" >&2
  echo "Keyword: $KEYWORD" >&2
  echo "Total Resources: $total_count" >&2
  echo "" >&2
  
  # Extract and display unique resource groups
  result_rgs=$(tail -n +2 "$OUT_FILE" | cut -d',' -f3 | sort -u | wc -l)
  echo "Resource Groups Found: $result_rgs" >&2
  echo "" >&2
  echo "Resource Groups:" >&2
  tail -n +2 "$OUT_FILE" | cut -d',' -f3 | sort -u | sed 's/^/  - /' >&2
  
  # Display sample types
  echo "" >&2
  result_types=$(tail -n +2 "$OUT_FILE" | cut -d',' -f3 | sort | uniq -c | sort -rn | head -5)
  echo "Top Resource Types:" >&2
  echo "$result_types" | awk '{print "  - " $3 " (" $1 ")"}' >&2
else
  echo "⚠ No resources found matching keyword '$KEYWORD'" >&2
  exit 0
fi

exit 0
