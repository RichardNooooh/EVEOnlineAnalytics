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

output "ansible_user" {
  description = "SSH user for Ansible to connect with"
  value       = var.ansible_user
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
