#!/usr/bin/env bash
set -euo pipefail

# Azure Inventory Exporter
# Structure:
#   azure-inventory/
#     subscription-name-sub-id/
#       _all-resources-flat.csv
#       _resource-groups.csv
#       _resource-types.csv
#       _enriched/
#         virtualMachines.csv
#         networkInterfaces.csv
#         virtualNetworks_subnets.csv
#         networkSecurityGroups_rules.csv
#         routeTables_routes.csv
#         disks.csv
#         publicIPAddresses.csv
#         privateEndpoints.csv
#         storageAccounts.csv
#         keyVaults.csv
#       resource-group-name/
#         Microsoft_Compute_virtualMachines.csv
#         Microsoft_Network_networkInterfaces.csv
#         ...

OUT_DIR="${1:-azure-inventory}"
PAGE_SIZE="${PAGE_SIZE:-1000}"

command -v az >/dev/null || { echo "Missing az CLI"; exit 1; }
command -v jq >/dev/null || { echo "Missing jq"; exit 1; }

az extension add --name resource-graph --only-show-errors 2>/dev/null || true

mkdir -p "$OUT_DIR"

safe_name() {
  echo "$1" \
    | sed 's#[/: ]#_#g' \
    | sed 's#[^A-Za-z0-9._-]#_#g'
}

csv_from_json_data() {
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

csv_append_from_json_data_no_header() {
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

graph_export_csv() {
  local sub_id="$1"
  local query_body="$2"
  local out_file="$3"
  local skip=0
  local first_page=true

  while true; do
    json=$(az graph query \
      --subscriptions "$sub_id" \
      --first "$PAGE_SIZE" \
      --skip "$skip" \
      -q "$query_body" \
      -o json)

    count=$(echo "$json" | jq '.data | length')
    [[ "$count" -eq 0 ]] && break

    if [[ "$first_page" == true ]]; then
      echo "$json" | csv_from_json_data > "$out_file"
      first_page=false
    else
      echo "$json" | csv_append_from_json_data_no_header >> "$out_file"
    fi

    [[ "$count" -lt "$PAGE_SIZE" ]] && break
    skip=$((skip + PAGE_SIZE))
  done
}

export_all_resources_flat() {
  local sub_id="$1"
  local out_file="$2"

  graph_export_csv "$sub_id" "
Resources
| order by id asc
| project
    subscriptionId,
    resourceGroup,
    name,
    type,
    location,
    id,
    tags = tostring(tags),
    sku = tostring(sku),
    kind = tostring(kind),
    managedBy = tostring(managedBy),
    identity = tostring(identity),
    provisioningState = tostring(properties.provisioningState),
    createdBy = tostring(systemData.createdBy),
    createdAt = tostring(systemData.createdAt),
    lastModifiedBy = tostring(systemData.lastModifiedBy),
    lastModifiedAt = tostring(systemData.lastModifiedAt),
    properties = tostring(properties)
" "$out_file"
}

export_resource_groups_summary() {
  local sub_id="$1"
  local out_file="$2"

  graph_export_csv "$sub_id" "
ResourceContainers
| where type =~ 'microsoft.resources/subscriptions/resourcegroups'
| order by name asc
| project
    subscriptionId,
    resourceGroup = name,
    location,
    id,
    tags = tostring(tags),
    provisioningState = tostring(properties.provisioningState)
" "$out_file"
}

export_resource_types_summary() {
  local sub_id="$1"
  local out_file="$2"

  graph_export_csv "$sub_id" "
Resources
| summarize resourceCount = count() by type
| order by type asc
| project type, resourceCount
" "$out_file"
}

export_generic_by_rg_and_type() {
  local sub_id="$1"
  local sub_folder="$2"

  rows=$(az graph query \
    --subscriptions "$sub_id" \
    --first 5000 \
    -q "
Resources
| summarize resourceCount = count() by resourceGroup, type
| order by resourceGroup asc, type asc
" -o json | jq -c '.data[]')

  echo "$rows" | while read -r row; do
    [[ -z "$row" ]] && continue

    rg=$(echo "$row" | jq -r '.resourceGroup')
    type=$(echo "$row" | jq -r '.type')

    rg_folder="$sub_folder/$(safe_name "$rg")"
    mkdir -p "$rg_folder"

    out_file="$rg_folder/$(safe_name "$type").csv"

    echo "    generic: $rg / $type"

    graph_export_csv "$sub_id" "
Resources
| where resourceGroup =~ '$rg'
| where type =~ '$type'
| order by id asc
| project
    subscriptionId,
    resourceGroup,
    name,
    type,
    location,
    id,
    tags = tostring(tags),
    sku = tostring(sku),
    kind = tostring(kind),
    managedBy = tostring(managedBy),
    identity = tostring(identity),
    provisioningState = tostring(properties.provisioningState),
    createdBy = tostring(systemData.createdBy),
    createdAt = tostring(systemData.createdAt),
    lastModifiedBy = tostring(systemData.lastModifiedBy),
    lastModifiedAt = tostring(systemData.lastModifiedAt),
    properties = tostring(properties)
" "$out_file"
  done
}

export_enriched() {
  local sub_id="$1"
  local enriched_folder="$2"

  mkdir -p "$enriched_folder"

  echo "    enriched: virtualMachines.csv"
  graph_export_csv "$sub_id" "
Resources
| where type =~ 'microsoft.compute/virtualmachines'
| order by id asc
| project
    subscriptionId,
    resourceGroup,
    vmName = name,
    location,
    vmSize = tostring(properties.hardwareProfile.vmSize),
    osType = tostring(properties.storageProfile.osDisk.osType),
    osDiskName = tostring(properties.storageProfile.osDisk.name),
    osDiskId = tostring(properties.storageProfile.osDisk.managedDisk.id),
    powerState = tostring(properties.extended.instanceView.powerState.displayStatus),
    provisioningState = tostring(properties.provisioningState),
    computerName = tostring(properties.osProfile.computerName),
    adminUsername = tostring(properties.osProfile.adminUsername),
    availabilitySetId = tostring(properties.availabilitySet.id),
    zone = tostring(zones),
    nicIds = tostring(properties.networkProfile.networkInterfaces),
    imagePublisher = tostring(properties.storageProfile.imageReference.publisher),
    imageOffer = tostring(properties.storageProfile.imageReference.offer),
    imageSku = tostring(properties.storageProfile.imageReference.sku),
    imageVersion = tostring(properties.storageProfile.imageReference.version),
    tags = tostring(tags),
    id
" "$enriched_folder/virtualMachines.csv"

  echo "    enriched: networkInterfaces.csv"
  graph_export_csv "$sub_id" "
Resources
| where type =~ 'microsoft.network/networkinterfaces'
| mv-expand ipconfig = properties.ipConfigurations
| order by id asc
| project
    subscriptionId,
    resourceGroup,
    nicName = name,
    location,
    enableAcceleratedNetworking = tostring(properties.enableAcceleratedNetworking),
    vmId = tostring(properties.virtualMachine.id),
    privateIpAddress = tostring(ipconfig.properties.privateIPAddress),
    privateIpAllocationMethod = tostring(ipconfig.properties.privateIPAllocationMethod),
    subnetId = tostring(ipconfig.properties.subnet.id),
    publicIpId = tostring(ipconfig.properties.publicIPAddress.id),
    nsgId = tostring(properties.networkSecurityGroup.id),
    macAddress = tostring(properties.macAddress),
    tags = tostring(tags),
    id
" "$enriched_folder/networkInterfaces.csv"

  echo "    enriched: virtualNetworks_subnets.csv"
  graph_export_csv "$sub_id" "
Resources
| where type =~ 'microsoft.network/virtualnetworks'
| mv-expand subnet = properties.subnets
| order by id asc
| project
    subscriptionId,
    resourceGroup,
    vnetName = name,
    location,
    vnetAddressPrefixes = tostring(properties.addressSpace.addressPrefixes),
    subnetName = tostring(subnet.name),
    subnetAddressPrefix = tostring(subnet.properties.addressPrefix),
    subnetAddressPrefixes = tostring(subnet.properties.addressPrefixes),
    subnetNsgId = tostring(subnet.properties.networkSecurityGroup.id),
    subnetRouteTableId = tostring(subnet.properties.routeTable.id),
    privateEndpointNetworkPolicies = tostring(subnet.properties.privateEndpointNetworkPolicies),
    privateLinkServiceNetworkPolicies = tostring(subnet.properties.privateLinkServiceNetworkPolicies),
    tags = tostring(tags),
    vnetId = id,
    subnetId = tostring(subnet.id)
" "$enriched_folder/virtualNetworks_subnets.csv"

  echo "    enriched: networkSecurityGroups_rules.csv"
  graph_export_csv "$sub_id" "
Resources
| where type =~ 'microsoft.network/networksecuritygroups'
| mv-expand rule = properties.securityRules
| order by id asc
| project
    subscriptionId,
    resourceGroup,
    nsgName = name,
    location,
    ruleName = tostring(rule.name),
    priority = tostring(rule.properties.priority),
    direction = tostring(rule.properties.direction),
    access = tostring(rule.properties.access),
    protocol = tostring(rule.properties.protocol),
    sourceAddressPrefix = tostring(rule.properties.sourceAddressPrefix),
    sourceAddressPrefixes = tostring(rule.properties.sourceAddressPrefixes),
    sourcePortRange = tostring(rule.properties.sourcePortRange),
    sourcePortRanges = tostring(rule.properties.sourcePortRanges),
    destinationAddressPrefix = tostring(rule.properties.destinationAddressPrefix),
    destinationAddressPrefixes = tostring(rule.properties.destinationAddressPrefixes),
    destinationPortRange = tostring(rule.properties.destinationPortRange),
    destinationPortRanges = tostring(rule.properties.destinationPortRanges),
    description = tostring(rule.properties.description),
    tags = tostring(tags),
    nsgId = id
" "$enriched_folder/networkSecurityGroups_rules.csv"

  echo "    enriched: routeTables_routes.csv"
  graph_export_csv "$sub_id" "
Resources
| where type =~ 'microsoft.network/routetables'
| mv-expand route = properties.routes
| order by id asc
| project
    subscriptionId,
    resourceGroup,
    routeTableName = name,
    location,
    disableBgpRoutePropagation = tostring(properties.disableBgpRoutePropagation),
    routeName = tostring(route.name),
    addressPrefix = tostring(route.properties.addressPrefix),
    nextHopType = tostring(route.properties.nextHopType),
    nextHopIpAddress = tostring(route.properties.nextHopIpAddress),
    tags = tostring(tags),
    routeTableId = id
" "$enriched_folder/routeTables_routes.csv"

  echo "    enriched: disks.csv"
  graph_export_csv "$sub_id" "
Resources
| where type =~ 'microsoft.compute/disks'
| order by id asc
| project
    subscriptionId,
    resourceGroup,
    diskName = name,
    location,
    diskState = tostring(properties.diskState),
    osType = tostring(properties.osType),
    diskSizeGB = tostring(properties.diskSizeGB),
    skuName = tostring(sku.name),
    skuTier = tostring(sku.tier),
    encryptionType = tostring(properties.encryption.type),
    diskEncryptionSetId = tostring(properties.encryption.diskEncryptionSetId),
    managedBy = tostring(managedBy),
    zones = tostring(zones),
    tags = tostring(tags),
    id
" "$enriched_folder/disks.csv"

  echo "    enriched: publicIPAddresses.csv"
  graph_export_csv "$sub_id" "
Resources
| where type =~ 'microsoft.network/publicipaddresses'
| order by id asc
| project
    subscriptionId,
    resourceGroup,
    publicIpName = name,
    location,
    ipAddress = tostring(properties.ipAddress),
    publicIpAllocationMethod = tostring(properties.publicIPAllocationMethod),
    publicIpAddressVersion = tostring(properties.publicIPAddressVersion),
    skuName = tostring(sku.name),
    skuTier = tostring(sku.tier),
    dnsFqdn = tostring(properties.dnsSettings.fqdn),
    idleTimeoutInMinutes = tostring(properties.idleTimeoutInMinutes),
    tags = tostring(tags),
    id
" "$enriched_folder/publicIPAddresses.csv"

  echo "    enriched: privateEndpoints.csv"
  graph_export_csv "$sub_id" "
Resources
| where type =~ 'microsoft.network/privateendpoints'
| order by id asc
| project
    subscriptionId,
    resourceGroup,
    privateEndpointName = name,
    location,
    subnetId = tostring(properties.subnet.id),
    networkInterfaces = tostring(properties.networkInterfaces),
    privateLinkServiceConnections = tostring(properties.privateLinkServiceConnections),
    manualPrivateLinkServiceConnections = tostring(properties.manualPrivateLinkServiceConnections),
    provisioningState = tostring(properties.provisioningState),
    tags = tostring(tags),
    id
" "$enriched_folder/privateEndpoints.csv"

  echo "    enriched: storageAccounts.csv"
  graph_export_csv "$sub_id" "
Resources
| where type =~ 'microsoft.storage/storageaccounts'
| order by id asc
| project
    subscriptionId,
    resourceGroup,
    storageAccountName = name,
    location,
    skuName = tostring(sku.name),
    skuTier = tostring(sku.tier),
    kind = tostring(kind),
    accessTier = tostring(properties.accessTier),
    allowBlobPublicAccess = tostring(properties.allowBlobPublicAccess),
    supportsHttpsTrafficOnly = tostring(properties.supportsHttpsTrafficOnly),
    minimumTlsVersion = tostring(properties.minimumTlsVersion),
    allowSharedKeyAccess = tostring(properties.allowSharedKeyAccess),
    publicNetworkAccess = tostring(properties.publicNetworkAccess),
    defaultAction = tostring(properties.networkAcls.defaultAction),
    bypass = tostring(properties.networkAcls.bypass),
    encryption = tostring(properties.encryption),
    tags = tostring(tags),
    id
" "$enriched_folder/storageAccounts.csv"

  echo "    enriched: keyVaults.csv"
  graph_export_csv "$sub_id" "
Resources
| where type =~ 'microsoft.keyvault/vaults'
| order by id asc
| project
    subscriptionId,
    resourceGroup,
    keyVaultName = name,
    location,
    tenantId = tostring(properties.tenantId),
    skuName = tostring(properties.sku.name),
    enableRbacAuthorization = tostring(properties.enableRbacAuthorization),
    enablePurgeProtection = tostring(properties.enablePurgeProtection),
    enableSoftDelete = tostring(properties.enableSoftDelete),
    softDeleteRetentionInDays = tostring(properties.softDeleteRetentionInDays),
    publicNetworkAccess = tostring(properties.publicNetworkAccess),
    defaultAction = tostring(properties.networkAcls.defaultAction),
    bypass = tostring(properties.networkAcls.bypass),
    accessPolicies = tostring(properties.accessPolicies),
    privateEndpointConnections = tostring(properties.privateEndpointConnections),
    tags = tostring(tags),
    id
" "$enriched_folder/keyVaults.csv"

  echo "    enriched: sqlServers.csv"
  graph_export_csv "$sub_id" "
Resources
| where type =~ 'microsoft.sql/servers'
| order by id asc
| project
    subscriptionId,
    resourceGroup,
    sqlServerName = name,
    location,
    administratorLogin = tostring(properties.administratorLogin),
    version = tostring(properties.version),
    publicNetworkAccess = tostring(properties.publicNetworkAccess),
    minimalTlsVersion = tostring(properties.minimalTlsVersion),
    privateEndpointConnections = tostring(properties.privateEndpointConnections),
    tags = tostring(tags),
    id
" "$enriched_folder/sqlServers.csv"

  echo "    enriched: sqlDatabases.csv"
  graph_export_csv "$sub_id" "
Resources
| where type =~ 'microsoft.sql/servers/databases'
| order by id asc
| project
    subscriptionId,
    resourceGroup,
    databaseName = name,
    location,
    status = tostring(properties.status),
    skuName = tostring(sku.name),
    skuTier = tostring(sku.tier),
    skuFamily = tostring(sku.family),
    skuCapacity = tostring(sku.capacity),
    maxSizeBytes = tostring(properties.maxSizeBytes),
    collation = tostring(properties.collation),
    zoneRedundant = tostring(properties.zoneRedundant),
    readScale = tostring(properties.readScale),
    tags = tostring(tags),
    id
" "$enriched_folder/sqlDatabases.csv"
}

main() {
  subs=$(az account list --query '[].{id:id,name:name}' -o json)

  echo "$subs" | jq -c '.[]' | while read -r sub; do
    sub_id=$(echo "$sub" | jq -r '.id')
    sub_name=$(echo "$sub" | jq -r '.name')

    sub_folder="$OUT_DIR/$(safe_name "$sub_name-$sub_id")"
    enriched_folder="$sub_folder/_enriched"

    mkdir -p "$sub_folder"

    echo "Subscription: $sub_name / $sub_id"

    echo "  summary: _all-resources-flat.csv"
    export_all_resources_flat "$sub_id" "$sub_folder/_all-resources-flat.csv"

    echo "  summary: _resource-groups.csv"
    export_resource_groups_summary "$sub_id" "$sub_folder/_resource-groups.csv"

    echo "  summary: _resource-types.csv"
    export_resource_types_summary "$sub_id" "$sub_folder/_resource-types.csv"

    export_enriched "$sub_id" "$enriched_folder"

    echo "  generic exports by resource group and resource type"
    export_generic_by_rg_and_type "$sub_id" "$sub_folder"
  done

  echo "Done: $OUT_DIR"
}

main