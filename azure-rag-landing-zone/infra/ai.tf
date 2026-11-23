# Azure OpenAI: private only, Entra ID only (API keys disabled)
resource "azurerm_cognitive_account" "openai" {
  name                          = "oai-${local.name}"
  location                      = local.openai_location
  resource_group_name           = azurerm_resource_group.this.name
  kind                          = "OpenAI"
  sku_name                      = "S0"
  custom_subdomain_name         = "oai-${local.name}"
  public_network_access_enabled = false
  local_auth_enabled            = false
  tags                          = local.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_cognitive_deployment" "chat" {
  name                 = var.chat_model.deployment
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.chat_model.name
    version = var.chat_model.version
  }

  sku {
    name     = var.chat_model.sku
    capacity = var.chat_model.capacity
  }
}

resource "azurerm_cognitive_deployment" "embeddings" {
  name                 = var.embedding_model.deployment
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.embedding_model.name
    version = var.embedding_model.version
  }

  sku {
    name     = var.embedding_model.sku
    capacity = var.embedding_model.capacity
  }

  depends_on = [azurerm_cognitive_deployment.chat] # deployments on one account are created serially
}

# Azure AI Search: private only, Entra ID only
resource "azurerm_search_service" "this" {
  name                          = "srch-${local.name}"
  location                      = var.location
  resource_group_name           = azurerm_resource_group.this.name
  sku                           = var.search_sku
  public_network_access_enabled = false
  local_authentication_enabled  = false
  semantic_search_sku           = "free"
  tags                          = local.tags

  identity {
    type = "SystemAssigned"
  }
}

# Private endpoints + private DNS for every data-plane endpoint
locals {
  private_endpoints = {
    openai = {
      resource_id = azurerm_cognitive_account.openai.id
      subresource = "account"
      dns_zone    = "privatelink.openai.azure.com"
    }
    search = {
      resource_id = azurerm_search_service.this.id
      subresource = "searchService"
      dns_zone    = "privatelink.search.windows.net"
    }
  }
}

resource "azurerm_private_dns_zone" "this" {
  for_each            = toset([for pe in local.private_endpoints : pe.dns_zone])
  name                = each.value
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "this" {
  for_each              = azurerm_private_dns_zone.this
  name                  = "link-${local.name}"
  resource_group_name   = azurerm_resource_group.this.name
  private_dns_zone_name = each.value.name
  virtual_network_id    = azurerm_virtual_network.this.id
  registration_enabled  = false
  tags                  = local.tags
}

resource "azurerm_private_endpoint" "this" {
  for_each            = local.private_endpoints
  name                = "pe-${each.key}-${local.name}"
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.pe.id
  tags                = local.tags

  private_service_connection {
    name                           = "psc-${each.key}"
    private_connection_resource_id = each.value.resource_id
    subresource_names              = [each.value.subresource]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.this[each.value.dns_zone].id]
  }
}
