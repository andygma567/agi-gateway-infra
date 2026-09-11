resource "digitalocean_vpc" "main" {
  name     = var.droplet_name
  region   = var.region
  ip_range = var.vpc_ip_range
}

resource "digitalocean_ssh_key" "main" {
  name       = var.droplet_name
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "digitalocean_droplet" "langfuse_litellm" {
  name     = var.droplet_name
  region   = var.region
  size     = var.droplet_size
  image    = var.droplet_image
  ssh_keys = [digitalocean_ssh_key.main.id]
  vpc_uuid = digitalocean_vpc.main.id
  tags     = var.tags

  # Backups and DO monitoring stay off (provider defaults).
  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {})
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
