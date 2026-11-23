# Least privilege, no keys anywhere:
#   API identity    -> read the search index; call the model only through APIM
#   ingest identity -> write the search index; call the model only through APIM
#   APIM identity   -> call Azure OpenAI

resource "azurerm_role_assignment" "apim_openai_user" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_api_management.this.identity[0].principal_id
}

resource "azurerm_role_assignment" "app_search_reader" {
  scope                = azurerm_search_service.this.id
  role_definition_name = "Search Index Data Reader"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_role_assignment" "ingest_search_contributor" {
  scope                = azurerm_search_service.this.id
  role_definition_name = "Search Index Data Contributor"
  principal_id         = azurerm_user_assigned_identity.ingest.principal_id
}

# Needed to create/update the index definition
resource "azurerm_role_assignment" "ingest_search_service_contributor" {
  scope                = azurerm_search_service.this.id
  role_definition_name = "Search Service Contributor"
  principal_id         = azurerm_user_assigned_identity.ingest.principal_id
}
