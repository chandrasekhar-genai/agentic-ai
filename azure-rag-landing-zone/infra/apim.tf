# API Management as the AI gateway: Entra ID auth for callers, per-identity token
# budgets, retries on 429/5xx, and managed-identity auth to a private Azure OpenAI.

resource "azurerm_public_ip" "apim" {
  name                = "pip-apim-${local.name}"
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "Standard"
  allocation_method   = "Static"
  domain_name_label   = "apim-${local.name}"
  tags                = local.tags
}

resource "azurerm_api_management" "this" {
  name                 = "apim-${local.name}"
  location             = var.location
  resource_group_name  = azurerm_resource_group.this.name
  publisher_name       = var.publisher_name
  publisher_email      = var.publisher_email
  sku_name             = var.apim_sku
  virtual_network_type = "External"
  public_ip_address_id = azurerm_public_ip.apim.id
  tags                 = local.tags

  virtual_network_configuration {
    subnet_id = azurerm_subnet.apim.id
  }

  identity {
    type = "SystemAssigned"
  }

  depends_on = [azurerm_subnet_network_security_group_association.apim]
}

resource "azurerm_api_management_logger" "appi" {
  name                = "appi"
  api_management_name = azurerm_api_management.this.name
  resource_group_name = azurerm_resource_group.this.name
  resource_id         = azurerm_application_insights.this.id

  application_insights {
    connection_string = azurerm_application_insights.this.connection_string
  }
}

resource "azurerm_api_management_backend" "openai" {
  name                = "azure-openai"
  api_management_name = azurerm_api_management.this.name
  resource_group_name = azurerm_resource_group.this.name
  protocol            = "http"
  url                 = "${azurerm_cognitive_account.openai.endpoint}openai"
}

resource "azurerm_api_management_api" "openai" {
  name                  = "azure-openai"
  api_management_name   = azurerm_api_management.this.name
  resource_group_name   = azurerm_resource_group.this.name
  revision              = "1"
  display_name          = "Azure OpenAI"
  path                  = "openai"
  protocols             = ["https"]
  subscription_required = false # callers authenticate with Entra ID tokens instead
}

resource "azurerm_api_management_api_operation" "post" {
  operation_id        = "post"
  api_name            = azurerm_api_management_api.openai.name
  api_management_name = azurerm_api_management.this.name
  resource_group_name = azurerm_resource_group.this.name
  display_name        = "POST any"
  method              = "POST"
  url_template        = "/*"
}

resource "azurerm_api_management_api_policy" "openai" {
  api_name            = azurerm_api_management_api.openai.name
  api_management_name = azurerm_api_management.this.name
  resource_group_name = azurerm_resource_group.this.name
  xml_content = templatefile("${path.module}/policies/openai.xml.tftpl", {
    tenant_id  = data.azurerm_client_config.current.tenant_id
    client_ids = [azurerm_user_assigned_identity.app.client_id, azurerm_user_assigned_identity.ingest.client_id]
    tpm        = var.tokens_per_minute_per_client
    backend_id = azurerm_api_management_backend.openai.name
  })
}

resource "azurerm_api_management_api_diagnostic" "openai" {
  identifier               = "applicationinsights"
  api_name                 = azurerm_api_management_api.openai.name
  api_management_name      = azurerm_api_management.this.name
  resource_group_name      = azurerm_resource_group.this.name
  api_management_logger_id = azurerm_api_management_logger.appi.id
  sampling_percentage      = 100
  always_log_errors        = true
  verbosity                = "information"
}
