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
    ansible = {
      source  = "ansible/ansible"
      version = "~> 1.4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.8.1"
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

# -----------------------------------------------------------------------------
# Local Values — SSH Key Path Resolution
# -----------------------------------------------------------------------------
# If ssh_key_path_ansible is not specified, default to ssh_key_path_proxmox
# -----------------------------------------------------------------------------
locals {
  ssh_key_path_ansible = coalesce(var.ssh_key_path_ansible, var.ssh_key_path_proxmox)

  postgresql_nodes = var.postgresql_vm_enabled ? {
    (var.postgresql_vm_name) = {
      node_name = var.postgresql_vm_node_name
      vm_id     = var.postgresql_vm_id
      ip_addr   = var.postgresql_vm_ip_addr
    }
  } : {}

  all_cloud_init_nodes = merge(var.k3s_nodes, local.postgresql_nodes)
  postgresql_vm_ip     = split("/", var.postgresql_vm_ip_addr)[0]
}
