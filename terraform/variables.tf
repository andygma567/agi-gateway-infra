variable "region" {
  description = "DigitalOcean region slug"
  type        = string
  default     = "nyc3"
}

variable "droplet_size" {
  description = "Droplet size slug"
  type        = string
  default     = "s-8vcpu-16gb"
}

variable "droplet_name" {
  description = "Droplet hostname / display name"
  type        = string
  default     = "langfuse-litellm-dev"
}

variable "droplet_image" {
  description = "Droplet image slug"
  type        = string
  default     = "ubuntu-24-04-x64"
}

variable "ssh_public_key_path" {
  description = "Path to the local SSH public key to register on DigitalOcean"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "tags" {
  description = "Tags applied to the droplet"
  type        = list(string)
  default     = ["dev", "langfuse", "litellm"]
}
