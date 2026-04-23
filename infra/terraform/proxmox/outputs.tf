# =============================================================================
# Outputs — k3s Cluster VMs
# =============================================================================

output "k3s_vm_ips" {
  description = "Map of k3s VM names to their IPv4 addresses"
  value = {
    for name, config in var.k3s_nodes : name => config.ip_addr
  }
}

output "k3s_vm_ids" {
  description = "Map of k3s VM names to their Proxmox VM IDs"
  value = {
    for name, vm in proxmox_virtual_environment_vm.k3s : name => vm.vm_id
  }
}

output "postgresql_vm_ip" {
  description = "IPv4 address for the external PostgreSQL VM"
  value       = var.postgresql_vm_enabled ? local.postgresql_vm_ip : null
}

output "postgresql_vm_id" {
  description = "Proxmox VM ID for the external PostgreSQL VM"
  value       = var.postgresql_vm_enabled ? proxmox_virtual_environment_vm.postgresql[var.postgresql_vm_name].vm_id : null
}

output "ansible_user" {
  description = "SSH user for Ansible to connect with"
  value       = var.ansible_user
}

output "ssh_key_path_proxmox" {
  description = "Path to the SSH private key used for Proxmox cloud-init (public key derived from this)"
  value       = var.ssh_key_path_proxmox
}

output "ssh_key_path_ansible" {
  description = "Path to the SSH private key used for Ansible connections to VMs"
  value       = local.ssh_key_path_ansible
}

output "ansible_inventory_path" {
  description = "Path to the generated Ansible inventory file (INI format)"
  value       = local_file.ansible_inventory.filename
}

output "postgresql_ansible_vars_path" {
  description = "Path to the generated Ansible host vars file for PostgreSQL credentials"
  value       = var.postgresql_vm_enabled ? local_sensitive_file.postgresql_ansible_vars_file[0].filename : null
}

output "airflow_db_env_path" {
  description = "Path to the generated Airflow database env file"
  value       = var.postgresql_vm_enabled ? local_sensitive_file.airflow_db_env_file[0].filename : null
}

output "ml_db_env_path" {
  description = "Path to the generated MLflow database env file"
  value       = var.postgresql_vm_enabled ? local_sensitive_file.ml_db_env_file[0].filename : null
}

output "ansible_inventory_snippet" {
  description = "Quick-reference for building your k3s-ansible inventory"
  value       = <<-EOF

    # Add to your k3s-ansible inventory (hosts.yml):
    # k3s_cluster:
    #   children:
    #     server:
    #       hosts:
    %{for name, config in var.k3s_nodes~}
    #         ${name}:
    #           ansible_host: ${split("/", config.ip_addr)[0]}
    %{endfor~}
    #   vars:
    #     ansible_user: ${var.ansible_user}

  EOF
}
