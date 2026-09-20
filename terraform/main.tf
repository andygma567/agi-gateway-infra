locals {
  ssh_public_key = trimspace(file(pathexpand(var.ssh_public_key_path)))
  ssh_key_body   = split(" ", local.ssh_public_key)[1]
}

# Account-wide keys are unique by fingerprint. A previous apply, the DO
# dashboard, or another stack may already have this laptop key (here:
# MacBook-Air-key). Creating it again returns 422 "SSH Key is already in use".
data "digitalocean_ssh_keys" "account" {}

locals {
  existing_ssh_keys = [
    for key in data.digitalocean_ssh_keys.account.ssh_keys : key
    if strcontains(key.public_key, local.ssh_key_body)
  ]
}

resource "digitalocean_ssh_key" "main" {
  count      = length(local.existing_ssh_keys) == 0 ? 1 : 0
  name       = var.droplet_name
  public_key = local.ssh_public_key
}

locals {
  ssh_key_id = (
    length(local.existing_ssh_keys) > 0
    ? local.existing_ssh_keys[0].id
    : digitalocean_ssh_key.main[0].id
  )
}

resource "digitalocean_droplet" "langfuse_litellm" {
  name     = var.droplet_name
  region   = var.region
  size     = var.droplet_size
  image    = var.droplet_image
  ssh_keys = [local.ssh_key_id]
  tags     = var.tags

  # Uses the region's default VPC. Backups and DO monitoring stay off (provider defaults).
}

resource "digitalocean_firewall" "main" {
  name = var.droplet_name

  droplet_ids = [digitalocean_droplet.langfuse_litellm.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "3000"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "4000"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
