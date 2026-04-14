# =============================================================================
# Data Sources
# =============================================================================

data "local_file" "ssh_public_key" {
  filename = "${var.ssh_key_path_proxmox}.pub"
}

# =============================================================================
# Cloud Image — downloaded to TrueNAS shared storage (single copy for all nodes)
# =============================================================================
# The cloud image is stored on TrueNAS NFS share (ID: "TrueNAS"), accessible
# from all Proxmox nodes. VMs import from this shared location.

resource "proxmox_download_file" "debian_generic_image" {
  content_type = "import"
  datastore_id = "TrueNAS"
  node_name    = "pve1" # Download via pve1, but file is on shared storage

  url = var.cloud_image_url

  checksum           = var.cloud_image_checksum
  checksum_algorithm = "sha512"

  verify = true

  lifecycle {
    prevent_destroy = true
  }
}

# =============================================================================
# Cloud-Init: User Data (generic — same for all VMs)
# =============================================================================
# This snippet configures the ansible user, SSH keys, essential packages,
# and enables qemu-guest-agent. Stored on TrueNAS shared storage so all VMs
# can reference the same file.
#
# NOTE: When using user_data_file_id, the custom config OVERWRITES Proxmox's
# generated cloud-init. Hostname is set separately via meta_data_file_id.

resource "proxmox_virtual_environment_file" "user_data" {
  content_type = "snippets"
  datastore_id = "TrueNAS"
  node_name    = "pve1" # Upload via pve1, but file is on shared storage

  source_raw {
    file_name = "k3s-user-data.yaml"
    data      = <<-EOF
      #cloud-config

      # ---------------------------------------------------------------
      # User Configuration
      # ---------------------------------------------------------------
      users:
        - default
        - name: ${var.ansible_user}
          groups:
            - sudo
          shell: /bin/bash
          sudo: ALL=(ALL) NOPASSWD:ALL
          lock_passwd: true
          ssh_authorized_keys:
            - ${trimspace(data.local_file.ssh_public_key.content)}

      # ---------------------------------------------------------------
      # Package Installation
      # ---------------------------------------------------------------
      package_update: true
      package_upgrade: true
      packages:
        - qemu-guest-agent
        - curl
        - gnupg
        - apt-transport-https
        - ca-certificates
        - open-iscsi
        - nfs-common
        - python3

      # ---------------------------------------------------------------
      # Post-Boot Commands
      # ---------------------------------------------------------------
      runcmd:
        - systemctl enable --now qemu-guest-agent
        # Signal that cloud-init completed successfully
        - echo "cloud-init done" > /tmp/cloud-init.done

      # ---------------------------------------------------------------
      # System Configuration
      # ---------------------------------------------------------------
      timezone: ${var.timezone}

      # Reboot after cloud-init to ensure guest agent registers with Proxmox
      power_state:
        mode: reboot
        timeout: 30
        condition: true
    EOF
  }
}

# =============================================================================
# Cloud-Init: Meta Data (per-VM — sets hostname)
# =============================================================================
# Separated from user_data so the user_data snippet stays generic.
# This is the pattern recommended by the bpg cloud-init guide for
# deploying multiple VMs (e.g., a Kubernetes cluster).
# Stored on TrueNAS shared storage.

resource "proxmox_virtual_environment_file" "meta_data" {
  for_each = var.k3s_nodes

  content_type = "snippets"
  datastore_id = "TrueNAS"
  node_name    = "pve1" # Upload via pve1, but files are on shared storage

  source_raw {
    file_name = "${each.key}-meta-data.yaml"
    data      = <<-EOF
      #cloud-config
      local-hostname: ${each.key}
    EOF
  }
}

# =============================================================================
# k3s Virtual Machines
# =============================================================================

resource "proxmox_virtual_environment_vm" "k3s" {
  for_each = var.k3s_nodes

  name        = each.key
  description = "k3s node — managed by OpenTofu"
  tags        = ["k3s", "opentofu", "eve-market"]
  node_name   = each.value.node_name
  vm_id       = each.value.vm_id

  # --------------------------------------------------------------------------
  # Guest Agent
  # --------------------------------------------------------------------------
  # Enabled because cloud-init installs and starts qemu-guest-agent.
  agent {
    enabled = true
  }

  # If agent fails to respond (e.g., during first boot before reboot),
  # force stop so opentofu destroy doesn't hang.
  stop_on_destroy = true

  # --------------------------------------------------------------------------
  # Boot Order
  # --------------------------------------------------------------------------
  startup {
    order      = "3"
    up_delay   = "60"
    down_delay = "60"
  }

  # --------------------------------------------------------------------------
  # CPU & Memory
  # --------------------------------------------------------------------------
  cpu {
    cores = var.vm_cpu_cores
    type  = "x86-64-v2-AES" # recommended for modern CPUs
  }

  memory {
    dedicated = var.vm_memory_mb
    floating  = var.vm_memory_mb # enable ballooning
  }

  # --------------------------------------------------------------------------
  # Boot Disk — imported from cloud image on TrueNAS
  # --------------------------------------------------------------------------
  disk {
    datastore_id = "local-lvm"
    import_from  = proxmox_download_file.debian_generic_image.id
    interface    = "virtio0"
    iothread     = true
    discard      = "on"
    size         = var.vm_disk_size_gb
    ssd          = true
  }

  # --------------------------------------------------------------------------
  # Serial Device — required for Debian 12 / Ubuntu to avoid kernel panic
  # on boot disk resize.
  # --------------------------------------------------------------------------
  serial_device {}

  # --------------------------------------------------------------------------
  # Network
  # --------------------------------------------------------------------------
  network_device {
    bridge  = var.vm_network_bridge
    vlan_id = var.vm_vlan_id
  }

  # --------------------------------------------------------------------------
  # Cloud-Init
  # --------------------------------------------------------------------------
  initialization {
    datastore_id = "local-lvm"

    ip_config {
      ipv4 {
        address = each.value.ip_addr
        gateway = var.gateway
      }
    }

    dns {
      servers = var.dns_servers
      domain  = var.dns_search_domain
    }

    user_data_file_id = proxmox_virtual_environment_file.user_data.id
    meta_data_file_id = proxmox_virtual_environment_file.meta_data[each.key].id
  }

  # --------------------------------------------------------------------------
  # Lifecycle
  # --------------------------------------------------------------------------
  lifecycle {
    ignore_changes = [
      # After first boot, cloud-init may alter the disk; don't fight it.
      disk[0].size,
    ]
  }
}

resource "random_password" "k3s_cluster_key" {
  length  = 32
  special = false
}

resource "random_password" "grafana_admin_password" {
  length  = 32
  special = false
}

resource "local_file" "k3s_cluster_key_file" {
  content         = random_password.k3s_cluster_key.result
  filename        = "${path.module}/../../ansible/inventory/k3s_cluster.key"
  file_permission = "0644"
}

resource "local_sensitive_file" "grafana_admin_env_file" {
  content         = <<-EOF
    admin-user=admin
    admin-password=${random_password.grafana_admin_password.result}
  EOF
  filename        = "${path.module}/../../.grafana-admin.env"
  file_permission = "0600"
}
