output "rag_api_url" {
  value = "https://${azurerm_container_app.rag.ingress[0].fqdn}"
}

output "apim_gateway_url" {
  value = azurerm_api_management.this.gateway_url
}

output "openai_endpoint" {
  value = azurerm_cognitive_account.openai.endpoint
}

output "search_endpoint" {
  value = "https://${azurerm_search_service.this.name}.search.windows.net"
}

output "ingest_job" {
  value = "az containerapp job start -n ${azurerm_container_app_job.ingest.name} -g ${azurerm_resource_group.this.name}"
}

output "ingest_job_name" {
  value = azurerm_container_app_job.ingest.name
}

output "resource_group_name" {
  value = azurerm_resource_group.this.name
}
