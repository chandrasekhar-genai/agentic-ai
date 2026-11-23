resource "azurerm_user_assigned_identity" "app" {
  name                = "id-rag-api-${local.name}"
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "ingest" {
  name                = "id-rag-ingest-${local.name}"
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.tags
}

resource "azurerm_container_app_environment" "this" {
  name                       = "cae-${local.name}"
  location                   = var.location
  resource_group_name        = azurerm_resource_group.this.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  infrastructure_subnet_id   = azurerm_subnet.apps.id
  tags                       = local.tags

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

locals {
  app_env = {
    RAG_MODE             = "azure"
    OPENAI_ENDPOINT      = azurerm_api_management.this.gateway_url
    CHAT_DEPLOYMENT      = var.chat_model.deployment
    EMBEDDING_DEPLOYMENT = var.embedding_model.deployment
    EMBEDDING_DIMENSIONS = tostring(var.embedding_model.dimensions)
    SEARCH_ENDPOINT      = "https://${azurerm_search_service.this.name}.search.windows.net"
    SEARCH_INDEX         = var.search_index
  }
}

# The RAG API
resource "azurerm_container_app" "rag" {
  name                         = "ca-rag-${local.name}"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = azurerm_resource_group.this.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  secret {
    name  = "appi-connection-string"
    value = azurerm_application_insights.this.connection_string
  }

  template {
    min_replicas = 1
    max_replicas = 5

    container {
      name   = "rag-api"
      image  = var.app_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.app.client_id
      }
      dynamic "env" {
        for_each = local.app_env
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "appi-connection-string"
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8080
        path      = "/healthz"
      }
      readiness_probe {
        transport = "HTTP"
        port      = 8080
        path      = "/healthz"
      }
    }

    http_scale_rule {
      name                = "http"
      concurrent_requests = "30"
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8080

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }

    dynamic "ip_security_restriction" {
      for_each = var.allowed_ip_ranges
      content {
        name             = "allow-${ip_security_restriction.key}"
        action           = "Allow"
        ip_address_range = ip_security_restriction.value
      }
    }
  }

  depends_on = [azurerm_role_assignment.app_search_reader]
}

# Ingestion runs as a job inside the VNet, because Search and OpenAI have no public endpoint.
#   az containerapp job start -n <job> -g <rg>
resource "azurerm_container_app_job" "ingest" {
  name                         = "caj-ingest-${local.name}"
  location                     = var.location
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = azurerm_container_app_environment.this.id
  replica_timeout_in_seconds   = 1800
  replica_retry_limit          = 1
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.ingest.id]
  }

  template {
    container {
      name    = "ingest"
      image   = var.app_image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "-m", "rag.ingest"]

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.ingest.client_id
      }
      dynamic "env" {
        for_each = local.app_env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }
}
