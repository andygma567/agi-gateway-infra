output "ipv4_address" {
  description = "Public IPv4 of the droplet — paste into inventory/hosts.yml as ansible_host"
  value       = digitalocean_droplet.langfuse_litellm.ipv4_address
}

output "droplet_id" {
  description = "DigitalOcean droplet ID"
  value       = digitalocean_droplet.langfuse_litellm.id
}

output "droplet_size" {
  description = "Droplet size slug"
  value       = digitalocean_droplet.langfuse_litellm.size
}
