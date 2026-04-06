# Proxmox k3s VM Provisioning

This OpenTofu/Terraform configuration provisions three k3s-ready VMs across a 3-node Proxmox cluster using cloud-init.

## What This Creates

- **3 VMs** (k3s-1, k3s-2, k3s-3) distributed across Proxmox nodes pve1, pve2, pve3
- **Cloud-init enabled** Debian 13 (Trixie) VMs with:
  - ansible user with sudo (passwordless)
  - SSH key authentication
  - qemu-guest-agent, NFS utils, iSCSI initiator
  - Static IP configuration
- **Specs per VM**: 4 CPU cores, 8 GB RAM, 40 GB disk

## Prerequisites

### On Your Proxmox Cluster

1. **API Token** — Create at Datacenter → Permissions → API Tokens:
   - Format: `USER@REALM!TOKENID=TOKEN-UUID`
   - Needs `Datastore.AllocateTemplate`, `VM.Allocate`, `VM.Config.*`, `SDN.Use`

2. **TrueNAS/NFS Storage** — A shared datastore accessible from all nodes:
   - Must have "Import" and "Snippets" content types enabled
   - Used for cloud images and cloud-init files
   - In this config, the datastore is named `"TrueNAS"`

3. **Network Bridge** — `vmbr0` (default) with VLAN support if using VLANs

4. **SSH Access** — The provider needs SSH access to upload cloud-init snippets:
   - SSH agent must have your key loaded, OR
   - Configure `ssh {}` block in provider config

### On Your Workstation

- [OpenTofu](https://opentofu.org/) or Terraform >= 1.11
- SSH key pair (default: `~/.ssh/id_ed25519.pub`)
- `cloud-init` knowledge (helpful but not required)

## Setup

### 1. Configure Variables

Copy the example and edit:

```bash
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values
```

**Key variables to set:**

| Variable | Description | Example |
|----------|-------------|---------|
| `proxmox_api_url` | Your Proxmox API endpoint | `https://pve1.normandy.internal:8006/` |
| `proxmox_api_token` | Your API token | `terraform@pve!opentofu=xxxxx` |
| `k3s_nodes` | VM names, node placement, IPs | See example file |
| `gateway` | Default gateway for VMs | `10.218.20.1` |
| `vm_vlan_id` | Your VLAN ID | `20` |
| `dns_servers` | DNS server list | `["10.218.20.90"]` |

### 2. Initialize

```bash
tofu init
```

### 3. Plan & Apply

```bash
tofu plan
tofu apply
```

After apply completes, the VMs will boot and cloud-init will run (takes ~1-3 minutes).

## Outputs

After apply, you'll get:

- `k3s_vm_ips` — Map of VM names to IP addresses
- `k3s_vm_ids` — Proxmox VM IDs
- `ansible_inventory_snippet` — Ready-to-use inventory for k3s-ansible

## Next Steps

Once VMs are running, proceed to [infra/ansible/](../../ansible/) to bootstrap the k3s cluster.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Permission denied" on snippet upload | Ensure SSH agent has your key: `ssh-add ~/.ssh/id_ed25519` |
| VM boots but no IP | Check VLAN ID matches your network config |
| Cloud-init not running | Verify "snippets" content type enabled on datastore |
| Apply hangs on destroy | Set `stop_on_destroy = true` (already in config) |
| Can SSH in but long terraform times / no qemu | [It's probably DNS](https://www.cyberciti.biz/humour/a-haiku-about-dns/) |

## Files

- `main.tf` — Provider and terraform configuration
- `proxmox.tf` — All resources (VMs, cloud-init, images)
- `variables.tf` — All configurable variables
- `outputs.tf` — Useful outputs post-apply
- `terraform.tfvars.example` — Template for your config
