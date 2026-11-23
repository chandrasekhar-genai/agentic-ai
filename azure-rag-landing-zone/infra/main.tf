locals {
  name            = var.name
  openai_location = coalesce(var.openai_location, var.location)
  tags = merge(var.tags, {
    workload   = "rag"
    managed_by = "terraform"
  })
}

resource "azurerm_resource_group" "this" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-${local.name}"
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_application_insights" "this" {
  name                = "appi-${local.name}"
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
  workspace_id        = azurerm_log_analytics_workspace.this.id
  application_type    = "web"
  tags                = local.tags
}

# Platform logs for the AI services and the gateway (prompt/response bodies are not logged)
resource "azurerm_monitor_diagnostic_setting" "this" {
  for_each = {
    openai = azurerm_cognitive_account.openai.id
    search = azurerm_search_service.this.id
    apim   = azurerm_api_management.this.id
  }

  name                       = "diag-${each.key}"
  target_resource_id         = each.value
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id

  enabled_log {
    category_group = "allLogs"
  }
}
