# =============================================================================
# k3s Cluster VMs — Proxmox Provisioning via Cloud-Init
# =============================================================================
# Provisions one k3s-ready VM per Proxmox node (pve1, pve2, pve3).
# Cloud-init handles day-zero bootstrap: ansible user, SSH keys, qemu-guest-agent.
# Ansible handles day-one config: k3s installation via k3s-io/k3s-ansible.
#
# Prerequisites:
#   - "Snippets" and "Import" content types enabled on "local" storage (each node)
#   - SSH access configured for the provider (required for snippet upload via SFTP)
#   - An SSH public key file at the path specified by var.ssh_public_key_path
# =============================================================================

terraform {
  required_version = "~> 1.11"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = ">= 0.100.0"
    }
  }
}

provider "proxmox" {
  endpoint  = var.proxmox_api_url
  api_token = var.proxmox_api_token
  insecure  = var.proxmox_tls_insecure

  ssh {
    agent    = true
    username = var.proxmox_ssh_user
  }
}
