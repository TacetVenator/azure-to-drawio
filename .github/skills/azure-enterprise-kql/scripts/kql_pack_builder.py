#!/usr/bin/env python3
"""Generate starter KQL query packs by topic for Azure diagnostics."""

import argparse
import json

KQL_PACKS = {
    "inventory": [
        {
            "title": "Resource Count by Type",
            "query": "Resources | summarize count() by type | order by count_ desc",
        },
        {
            "title": "Resource Count by Resource Group",
            "query": "Resources | summarize count() by resourceGroup | order by count_ desc",
        },
    ],
    "governance": [
        {
            "title": "Resources Missing Tags",
            "query": "Resources | where isnull(tags) or array_length(bag_keys(tags)) == 0 | project id, name, type, resourceGroup",
        },
        {
            "title": "Policy Assignment Inventory",
            "query": "PolicyResources | where type =~ 'microsoft.authorization/policyassignments' | project name, id, properties",
        },
    ],
    "cost": [
        {
            "title": "SKU Distribution",
            "query": "Resources | extend sku=tostring(sku.name) | summarize count() by type, sku | order by count_ desc",
        },
        {
            "title": "Potential Idle Public IPs",
            "query": "Resources | where type =~ 'microsoft.network/publicipaddresses' | where tostring(properties.ipConfiguration.id) == '' | project id, name, resourceGroup",
        },
    ],
    "network": [
        {
            "title": "VNet Inventory",
            "query": "Resources | where type =~ 'microsoft.network/virtualnetworks' | project id, name, location, resourceGroup",
        },
        {
            "title": "NSG Rule Count",
            "query": "Resources | where type =~ 'microsoft.network/networksecuritygroups' | extend rules=array_length(properties.securityRules) | project name, resourceGroup, rules",
        },
    ],
    "security": [
        {
            "title": "Key Vault Public Access",
            "query": "Resources | where type =~ 'microsoft.keyvault/vaults' | project name, resourceGroup, publicNetworkAccess=tostring(properties.publicNetworkAccess)",
        },
        {
            "title": "Storage Public Access",
            "query": "Resources | where type =~ 'microsoft.storage/storageaccounts' | project name, resourceGroup, allowBlobPublicAccess=tostring(properties.allowBlobPublicAccess)",
        },
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Azure KQL pack generator")
    parser.add_argument("--topic", choices=sorted(KQL_PACKS.keys()), required=True)
    args = parser.parse_args()

    output = {
        "topic": args.topic,
        "queries": KQL_PACKS[args.topic],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
