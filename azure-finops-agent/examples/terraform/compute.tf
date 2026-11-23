resource "azurerm_linux_virtual_machine" "app_prod_01" {
  name                  = "vm-app-prod-01"
  resource_group_name   = azurerm_resource_group.app_prod.name
  location              = var.location
  size                  = "Standard_D16s_v5"
  admin_username        = "azureuser"
  network_interface_ids = [azurerm_network_interface.app_prod_01.id]

  admin_ssh_key {
    username   = "azureuser"
    public_key = var.ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  tags = { env = "prod", owner = "app-team" }
}

resource "azurerm_linux_virtual_machine" "build_dev_01" {
  name                  = "vm-build-dev-01"
  resource_group_name   = azurerm_resource_group.build_dev.name
  location              = var.location
  size                  = "Standard_D4s_v5"
  admin_username        = "azureuser"
  network_interface_ids = [azurerm_network_interface.build_dev_01.id]

  admin_ssh_key {
    username   = "azureuser"
    public_key = var.ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  tags = { env = "dev", owner = "platform" }
}
