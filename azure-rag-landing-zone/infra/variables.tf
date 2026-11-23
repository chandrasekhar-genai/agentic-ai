variable "name" {
  description = "Short workload name used in resource names, e.g. rag-dev"
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,14}$", var.name))
    error_message = "3-15 chars: lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "location" {
  description = "Region for the network, app and search, e.g. uaenorth"
  type        = string
}

variable "openai_location" {
  description = "Region for Azure OpenAI. Defaults to var.location; check model availability per region."
  type        = string
  default     = null
}

variable "vnet_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "apim_sku" {
  description = "Developer_1 for non-production, Premium_1 (or more units) for production"
  type        = string
  default     = "Developer_1"
}

variable "publisher_name" {
  type = string
}

variable "publisher_email" {
  type = string
}

variable "chat_model" {
  type = object({
    deployment = string
    name       = string
    version    = string
    sku        = string
    capacity   = number
  })
  default = {
    deployment = "chat"
    name       = "gpt-4o"
    version    = "2024-11-20"
    sku        = "Standard"
    capacity   = 30
  }
}

variable "embedding_model" {
  type = object({
    deployment = string
    name       = string
    version    = string
    sku        = string
    capacity   = number
    dimensions = number
  })
  default = {
    deployment = "embeddings"
    name       = "text-embedding-3-large"
    version    = "1"
    sku        = "Standard"
    capacity   = 50
    dimensions = 1024
  }
}

variable "search_sku" {
  description = "basic or higher (private endpoints are not available on free)"
  type        = string
  default     = "basic"
}

variable "search_index" {
  type    = string
  default = "docs"
}

variable "tokens_per_minute_per_client" {
  description = "Azure OpenAI token budget per calling identity, enforced at the APIM gateway"
  type        = number
  default     = 20000
}

variable "app_image" {
  description = "RAG API image (built by this repo's deploy workflow)"
  type        = string
  default     = "ghcr.io/chandrasekhar-genai/azure-rag-landing-zone:latest"
}

variable "allowed_ip_ranges" {
  description = "CIDRs allowed to reach the RAG API ingress. Empty = no IP restriction."
  type        = list(string)
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
