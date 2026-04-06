# =============================================================================
# Variables — k3s Cluster VMs
# =============================================================================

# -----------------------------------------------------------------------------
# Node Configuration
# -----------------------------------------------------------------------------

variable "k3s_nodes" {
  description = "Map of k3s node configurations (name -> node_name, vm_id, ip_addr)"
  type = map(object({
    node_name = string
    vm_id     = number
    ip_addr   = string
  }))
  default = {
    "k3s-1" = {
      node_name = "pve1"
      vm_id     = 201
      ip_addr   = "10.218.20.201/24"
    }
    "k3s-2" = {
      node_name = "pve2"
      vm_id     = 202
      ip_addr   = "10.218.20.202/24"
    }
    "k3s-3" = {
      node_name = "pve3"
      vm_id     = 203
      ip_addr   = "10.218.20.203/24"
    }
  }
}

variable "gateway" {
  description = "Default gateway for k3s VMs"
  type        = string
  default     = "10.218.20.1"
}

# -----------------------------------------------------------------------------
# Proxmox Connection
# -----------------------------------------------------------------------------

variable "proxmox_api_url" {
  description = "Proxmox API endpoint URL (e.g., https://pve1.normandy.internal:8006/)"
  type        = string
}

variable "proxmox_api_token" {
  description = "Proxmox API token in format 'USER@REALM!TOKENID=TOKEN-UUID'"
  type        = string
  sensitive   = true
}

variable "proxmox_tls_insecure" {
  description = "Skip TLS certificate verification (set false if using trusted certs)"
  type        = bool
  default     = false
}

variable "proxmox_ssh_user" {
  description = "SSH user for Proxmox node access (required for snippet uploads via SFTP)"
  type        = string
  default     = "root"
}

# -----------------------------------------------------------------------------
# SSH & User Configuration
# -----------------------------------------------------------------------------

variable "ssh_key_path_proxmox" {
  description = "Path to the SSH private key for Proxmox cloud-init (public key will be derived by appending .pub)"
  type        = string
  default     = "~/.ssh/id_ed25519"
}

variable "ssh_key_path_ansible" {
  description = "Path to the SSH private key for Ansible to use when connecting to VMs. Defaults to the same key as Proxmox."
  type        = string
  default     = null  # Will be resolved to ssh_key_path_proxmox in local values
}

variable "ansible_user" {
  description = "Username for the Ansible service account on each VM"
  type        = string
  default     = "ansible"
}

variable "timezone" {
  description = "Timezone for the VMs"
  type        = string
  default     = "UTC"
}

# -----------------------------------------------------------------------------
# Cloud Image
# -----------------------------------------------------------------------------

variable "cloud_image_url" {
  description = "URL of the Ubuntu cloud image to download"
  type        = string
  default     = "https://cloud.debian.org/images/cloud/trixie/20260402-2435/debian-13-generic-amd64-20260402-2435.qcow2"
}

variable "cloud_image_checksum" {
  description = "SHA512 checksum of the cloud image"
  type        = string
  default     = "584b03fd81dd85247a20fa2f1ea5ceae53094a52f62d0f9fa9ee7a2826e18c3734a77f801b110b9af79d0ea593f99c25936f7cf65eff0562eabc6223b861110a"
}

# -----------------------------------------------------------------------------
# VM Sizing
# -----------------------------------------------------------------------------

variable "vm_cpu_cores" {
  description = "Number of CPU cores per k3s VM"
  type        = number
  default     = 4
}

variable "vm_memory_mb" {
  description = "Dedicated memory in MB per k3s VM"
  type        = number
  default     = 10240 # ~10 GB — leaves ~3 GB for Proxmox + LXCs per 16 GB node
}

variable "vm_disk_size_gb" {
  description = "Boot disk size in GB per k3s VM"
  type        = number
  default     = 40
}

# -----------------------------------------------------------------------------
# Networking
# -----------------------------------------------------------------------------

variable "vm_network_bridge" {
  description = "Proxmox network bridge for VM NICs"
  type        = string
  default     = "vmbr0"
}

variable "vm_vlan_id" {
  description = "VLAN ID for the k3s VMs (your core VLAN)"
  type        = number
  default     = 20
}

variable "dns_servers" {
  description = "DNS server IPs for the VMs"
  type        = list(string)
  default     = ["10.218.20.90"]
}

variable "dns_search_domain" {
  description = "DNS search domain"
  type        = string
  default     = "normandy.internal"
}
