# Azure Keyword Search Scripts

Two scripts for exporting Azure resources matching a keyword to CSV format.

## Scripts

### 1. `azure-keyword-search.sh` (Basic)

Lightweight search with essential resource information.

**Usage:**
```bash
./azure-keyword-search.sh [KEYWORD] [OUTPUT_FILE]
```

**Examples:**
```bash
# Default: search for "ERP"
./azure-keyword-search.sh

# Search for "PROD"
./azure-keyword-search.sh "PROD"

# Custom output file
./azure-keyword-search.sh "STAGING" "staging-resources.csv"

# Custom subscription
SUBSCRIPTION_ID="12345678-1234-1234-1234-123456789012" ./azure-keyword-search.sh "ERP"
```

**Output Columns:**
- `ResourceId`: Full resource ID
- `Name`: Resource name
- `ResourceGroup`: Resource group name
- `Tags`: JSON-formatted tags
- `Region`: Azure region

### 2. `azure-keyword-search-extended.sh` (Extended - Recommended for large exports)

Comprehensive search with extended resource metadata. **Handles large result sets with pagination** (tested with 6000+ resources).

**Usage:**
```bash
./azure-keyword-search-extended.sh [KEYWORD] [OUTPUT_FILE]
```

**Examples:**
```bash
# Default: search for "ERP" with pagination
./azure-keyword-search-extended.sh

# Search for "PROD"
./azure-keyword-search-extended.sh "PROD"

# Custom output file
./azure-keyword-search-extended.sh "LEGACY" "legacy-resources.csv"

# Adjust page size for large migrations (default: 1000)
PAGE_SIZE=2000 ./azure-keyword-search-extended.sh "ERP"

# Custom subscription
SUBSCRIPTION_ID="12345678-1234-1234-1234-123456789012" ./azure-keyword-search-extended.sh "ERP"
```

**Output Columns:**
- `ResourceId`: Full resource ID
- `Name`: Resource name
- `Type`: Resource type (e.g., `Microsoft.Compute/virtualMachines`)
- `ResourceGroup`: Resource group name
- `Region`: Azure region
- `TenantId`: Tenant ID
- `ManagedBy`: ID of managing resource (if applicable)
- `Kind`: Resource kind
- `SkuName`: SKU name
- `SkuTier`: SKU tier (Standard, Premium, etc.)
- `SkuCapacity`: SKU capacity
- `IdentityType`: Managed identity type
- `IdentityPrincipalId`: Managed identity principal ID
- `IdentityTenantId`: Managed identity tenant ID
- `CreatedDate`: Resource creation date
- `LastModifiedDate`: Resource last modification date
- `ProvisioningState`: Current provisioning state
- `Zones`: Availability zones
- `Tags`: JSON-formatted tags

## Search Behavior

Both scripts search for the keyword in:
1. **Resource Group names** - exact substring match
2. **Tag values** - exact substring match
3. **Tag keys** - exact substring match

Results are deduplicated (distinct) when a resource matches multiple criteria.

## Prerequisites

- Azure CLI (`az`) - [Install](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
- `jq` - [Install](https://stedolan.github.io/jq/download/)
- Resource Graph extension (installed automatically)
- Appropriate Azure permissions to read resources

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SUBSCRIPTION_ID` | Current default | Target subscription |
| `PAGE_SIZE` | 1000 | Results per page (extended script only) |

## Migration Use Cases

### Finding all ERP resources
```bash
./azure-keyword-search-extended.sh "ERP"
```

### Exporting PROD resources for audit
```bash
./azure-keyword-search-extended.sh "PROD" "prod-audit-$(date +%Y%m%d).csv"
```

### Multi-environment export
```bash
for env in PROD STAGING UAT DEV; do
  ./azure-keyword-search-extended.sh "$env" "resources-$env.csv"
done
```

## Output Format

CSV with header row. All special characters in fields are properly escaped per RFC 4180.

**Example:**
```
ResourceId,Name,Type,ResourceGroup,Region,TenantId,ManagedBy,Kind,SkuName,SkuTier,SkuCapacity,IdentityType,IdentityPrincipalId,IdentityTenantId,CreatedDate,LastModifiedDate,ProvisioningState,Zones,Tags
/subscriptions/12345678-1234-1234-1234-123456789012/resourceGroups/erp-rg/providers/Microsoft.Compute/virtualMachines/erp-vm-01,erp-vm-01,Microsoft.Compute/virtualMachines,erp-rg,eastus,12345678-1234-1234-1234-123456789012,,,,,,,,,,2024-01-15T10:30:00.000Z,2024-03-20T14:22:15.000Z,Succeeded,,"{""environment"":""ERP"",""cost-center"":""12345""}"
```

## Troubleshooting

### "Missing az CLI"
Install: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli

### "Missing jq"
Install: https://stedolan.github.io/jq/download/

### No results found
- Verify the keyword exists in your subscription
- Check you have read permissions on all resources
- Try with a broader keyword

### Timeout on large migrations
- Reduce `PAGE_SIZE` if network is slow
- Run during off-peak hours
- Consider splitting by resource type if needed

## Notes

- The extended script automatically paginates through large result sets
- Both scripts exit cleanly with status 0 even if no results are found
- All timestamps use ISO 8601 format with UTC timezone
- Resource properties are JSON-encoded where applicable
