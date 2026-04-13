# Proxmox k3s VM Provisioning

This OpenTofu configuration provisions three k3s-ready VMs across a 3-node Proxmox
cluster using cloud-init. It also generates an Ansible inventory for cluster
bootstrap.

## What This Creates

- **3 VMs** distributed across Proxmox nodes `pve1`, `pve2`, and `pve3`
- **Cloud-init enabled** Debian 13 VMs with:
  - `ansible` user with passwordless sudo
  - SSH key authentication
  - qemu guest agent, NFS utils, iSCSI initiator
  - static IP configuration
- **Specs per VM by default**: 4 CPU cores, 10 GB RAM, 40 GB disk
- **Ansible inventory** auto-generated at `../../ansible/inventory/hosts.ini`

## Prerequisites

### On Your Proxmox Cluster

1. **API Token** - Create at Datacenter -> Permissions -> API Tokens.
2. **TrueNAS/NFS datastore** - Shared across Proxmox nodes and enabled for imports and snippets.
3. **Network bridge** - `vmbr0` with VLAN support if needed.
4. **SSH access** - Required for snippet upload.

The downstream k3s cluster uses NFS for shared Parquet datasets, manifests, MLflow
artifacts, and Airflow logs. It does not use NFS as a shared mutable DuckDB warehouse.

### On Your Workstation

- OpenTofu or Terraform >= 1.11
- SSH key pair

## Setup

### 1. Configure Variables

```bash
cp terraform.tfvars.example terraform.tfvars
```

Edit the file with your Proxmox API URL, token, VM IPs, VLAN settings, DNS servers,
and SSH key paths.

### 2. Initialize

```bash
tofu init
```

### 3. Plan and Apply

```bash
tofu plan
tofu apply
```

After apply completes:

1. The VMs boot and cloud-init runs.
2. An Ansible inventory file is generated at `../../ansible/inventory/hosts.ini`.
3. A local `../../.grafana-admin.env` file is generated for Grafana admin credential
   bootstrapping.

## Outputs

| Output | Description |
|---|---|
| `k3s_vm_ips` | Map of VM names to IP addresses |
| `k3s_vm_ids` | Proxmox VM IDs |
| `ansible_inventory_path` | Path to generated INI inventory |
| `ssh_key_path_proxmox` | SSH private key used for cloud-init |
| `ssh_key_path_ansible` | SSH private key used for Ansible |
| `ansible_inventory_snippet` | YAML-formatted reference for k3s-ansible |

## Ansible Integration

This configuration uses the `ansible/ansible` provider to:

1. Create `ansible_host` resources for each VM.
2. Create an `ansible_group` resource named `k3s_servers`.
3. Generate a local INI inventory file at `../../ansible/inventory/hosts.ini`.

## Next Steps

Once VMs are running and the inventory is generated:

```bash
cd ../../ansible
ansible-galaxy collection install -r requirements.yml
ansible-playbook bootstrap.yml
```

## Troubleshooting

| Issue | Solution |
|---|---|
| Permission denied on snippet upload | Ensure `ssh-agent` has your key loaded |
| VM boots but no IP | Check VLAN configuration |
| Cloud-init not running | Verify `snippets` content type on the datastore |
| Apply hangs on destroy | Confirm `stop_on_destroy = true` |
| Inventory file not generated | Ensure `../../ansible/inventory/` exists |

## Files

- `main.tf` - provider configuration
- `proxmox.tf` - VM resources, cloud-init, images
- `ansible.tf` - dynamic inventory generation
- `variables.tf` - configurable variables
- `outputs.tf` - useful outputs post-apply
- `terraform.tfvars.example` - configuration template
