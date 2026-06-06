# Tools Repository

A collection of utility and automation scripts.

## Directory Structure

* **[pve-tools/](file:///Users/mahesh/antigravity/pve-tools)**: Management and automation tools for Proxmox VE (PVE) environments.
  * **[update_containers.py](file:///Users/mahesh/antigravity/pve-tools/update_containers.py)**: Automates running commands (like system updates) across running LXC containers.
  * **[README.md](file:///Users/mahesh/antigravity/pve-tools/README.md)**: Detailed instructions for the Proxmox tools.

---

## Featured Tool: Proxmox LXC Container Update Automation

Located in `pve-tools/`, `update_containers.py` is a zero-dependency Python 3 script that automates updates (or custom command execution) across all running LXC containers in a Proxmox VE cluster.

### Advanced Features Added Recently:
* **Interactive Stdin Simulation**: Automatically inputs a newline (simulates hitting **Enter**) by default to proceed with prompts (e.g. confirming updates). You can customize the input using the `--input` / `-i` flag (e.g. `-i "1\n"`).
* **Graceful Cancellation**: Pressing `Ctrl+C` cleanly aborts the process, marks the active container as `CANCELLED`, lists remaining containers as `SKIPPED`, and outputs the execution summary table of what succeeded up to that point.

### Quick Usage

1. Make the script executable:
   ```bash
   chmod +x pve-tools/update_containers.py
   ```

2. Run a dry run to preview targeted containers:
   ```bash
   python3 pve-tools/update_containers.py --dry-run
   ```

3. Update all containers (automatically simulates pressing Enter for prompt confirmation):
   ```bash
   python3 pve-tools/update_containers.py
   ```

4. Run specific commands (e.g. standard APT update):
   ```bash
   python3 pve-tools/update_containers.py --cmd "apt-get update && apt-get upgrade -y"
   ```

For advanced filtering, whitelist/blacklist VMIDs, and cross-node cluster routing details, check out the [Proxmox Tools README](file:///Users/mahesh/antigravity/pve-tools/README.md).

---

## License

This repository is licensed under the MIT License. Feel free to modify and customize it for your home lab or production infrastructure.
