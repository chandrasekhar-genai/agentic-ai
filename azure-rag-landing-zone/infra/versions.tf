terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.20"
    }
  }

  # backend "azurerm" {}  # configured per environment: terraform init -backend-config=env/<env>.backend.hcl
}

provider "azurerm" {
  features {}
  storage_use_azuread = true
}

data "azurerm_client_config" "current" {}
