#!/usr/bin/env python3
import sys
import os
import json
import subprocess
import argparse
import shlex
import time

def run_command(cmd, ssh_host=None):
    """
    Runs a command either locally or remotely via SSH.
    cmd can be a list of args or a string.
    Returns (stdout, stderr, returncode).
    """
    if ssh_host:
        # For remote execution via SSH:
        # If cmd is a list, we quote its elements and join them to form a single shell command.
        if isinstance(cmd, list):
            cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
        else:
            cmd_str = cmd
        ssh_cmd = ["ssh", ssh_host, cmd_str]
        result = subprocess.run(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.stdout, result.stderr, result.returncode
    else:
        # Local execution
        shell = isinstance(cmd, str)
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=shell)
        return result.stdout, result.stderr, result.returncode
def initialize_sudo(ssh_host=None, use_sudo=False):
    """
    Initializes sudo access by running 'sudo -v' (validate).
    This allows the user to enter their password interactively if it's not cached.
    Subsequent commands using sudo will then succeed without prompting.
    """
    if not use_sudo:
        return True
        
    print("Validating sudo credentials on Proxmox host. You may be prompted for a password...")
    if ssh_host:
        # We must use -t to allocate a terminal for the password prompt
        cmd = ["ssh", "-t", ssh_host, "sudo -v"]
    else:
        cmd = ["sudo", "-v"]
        
    # Run without redirecting stdout/stderr/stdin so the password prompt is visible
    result = subprocess.run(cmd)
    return result.returncode == 0

def get_entrypoint_hostname(ssh_host=None):
    """
    Gets the hostname of the Proxmox node we connect to.
    This helps determine if we need to SSH to another node in the cluster or if we are already on it.
    """
    stdout, _, code = run_command(["hostname"], ssh_host)
    if code == 0:
        return stdout.strip()
    return None

def list_containers(ssh_host=None, use_sudo=False):
    """
    Uses pvesh to query the cluster resources and returns list of LXC containers.
    """
    # pvesh get /cluster/resources --output-format json
    cmd = ["pvesh", "get", "/cluster/resources", "--output-format", "json"]
    if use_sudo:
        cmd.insert(0, "sudo")
    stdout, stderr, code = run_command(cmd, ssh_host)
    if code != 0:
        print(f"Error querying cluster resources via pvesh: {stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    
    try:
        resources = json.loads(stdout)
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON output from pvesh: {e}", file=sys.stderr)
        print(f"Output received was:\n{stdout}", file=sys.stderr)
        sys.exit(1)
        
    # Filter only running LXC containers
    containers = []
    for res in resources:
        if res.get("type") == "lxc":
            containers.append({
                "vmid": res.get("vmid"),
                "name": res.get("name"),
                "node": res.get("node"),
                "status": res.get("status"),
            })
    return containers

def main():
    parser = argparse.ArgumentParser(
        description="Automate command execution (like 'update') across Proxmox LXC containers."
    )
    parser.add_argument(
        "--host", "-H",
        default="root@pve.home.local",
        help="Proxmox host to SSH into (default: root@pve.home.local). Pass 'local' to run locally on the PVE host."
    )
    parser.add_argument(
        "--cmd", "-C",
        default="update",
        help="Command to run inside each container (default: 'update')."
    )
    parser.add_argument(
        "--containers", "-c",
        help="Comma-separated list of container VMIDs or names to update (whitelist)."
    )
    parser.add_argument(
        "--exclude", "-e",
        help="Comma-separated list of container VMIDs or names to exclude (blacklist)."
    )
    parser.add_argument(
        "--node", "-n",
        help="Only update containers on a specific Proxmox cluster node."
    )
    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="Show what containers would be updated and what commands would run without executing them."
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Shortcut to run locally on the Proxmox host (equivalent to --host local)."
    )
    parser.add_argument(
        "--sudo", "-s",
        action="store_true",
        help="Use sudo for Proxmox commands (needed if SSH user is not root)."
    )

    args = parser.parse_args()

    ssh_host = args.host
    if args.local or ssh_host.lower() == "local":
        ssh_host = None
        print("Running in LOCAL mode directly on the Proxmox host.")
    else:
        print(f"Running in REMOTE mode using SSH to connect to {ssh_host}.")

    # 0. Initialize sudo if requested
    if args.sudo:
        if not initialize_sudo(ssh_host, args.sudo):
            print("Error: Failed to validate sudo privileges. Exiting.", file=sys.stderr)
            sys.exit(1)

    # 1. Fetch entrypoint host's node name
    entrypoint_node = None
    if ssh_host:
        entrypoint_node = get_entrypoint_hostname(ssh_host)
        if entrypoint_node:
            print(f"Successfully connected to entrypoint node: '{entrypoint_node}'")
        else:
            print(f"Warning: Could not determine the hostname of {ssh_host}. Will assume it requires SSH for cross-node commands.")

    # 2. Get list of containers
    print("Fetching LXC containers from Proxmox...")
    all_containers = list_containers(ssh_host, use_sudo=args.sudo)
    
    if not all_containers:
        print("No LXC containers found on the Proxmox host/cluster.")
        return

    # Parse Whitelist / Blacklist
    whitelist = [c.strip() for c in args.containers.split(",")] if args.containers else None
    blacklist = [c.strip() for c in args.exclude.split(",")] if args.exclude else []

    # 3. Filter containers
    targets = []
    for c in all_containers:
        vmid_str = str(c["vmid"])
        name = c["name"]
        node = c["node"]
        status = c["status"]

        # Filter by node
        if args.node and node != args.node:
            continue

        # Filter by whitelist
        if whitelist:
            if vmid_str not in whitelist and name not in whitelist:
                continue

        # Filter by blacklist
        if vmid_str in blacklist or name in blacklist:
            continue

        # Check status (pct exec only works on running containers)
        if status != "running":
            # We print a message if they explicitly selected it, otherwise we silent skip
            if whitelist:
                print(f"Skipping container {vmid_str} ({name}) because it is not running (status: {status}).")
            continue

        targets.append(c)

    if not targets:
        print("No running containers matched the specified criteria.")
        return

    print(f"\nFound {len(targets)} running containers matching criteria:")
    for t in targets:
        print(f"  - VMID {t['vmid']}: {t['name']} (on node '{t['node']}')")
    
    if args.dry_run:
        print("\n=== DRY RUN MODE: No commands will be executed ===")
        for t in targets:
            # Construct command
            vmid = t["vmid"]
            node = t["node"]
            
            # Target cmd inside container shell
            container_cmd_str = f"/bin/sh -c {shlex.quote(args.cmd)}"
            pct_cmd = f"pct exec {vmid} -- {container_cmd_str}"
            if args.sudo:
                pct_cmd = f"sudo {pct_cmd}"
            
            # Cross-node command if needed
            if entrypoint_node and node != entrypoint_node:
                ssh_prefix = "sudo ssh" if args.sudo else "ssh"
                final_pve_cmd = f"{ssh_prefix} -o StrictHostKeyChecking=no root@{node} {shlex.quote(pct_cmd)}"
            else:
                final_pve_cmd = pct_cmd

            if ssh_host:
                print(f"Container {vmid} ({t['name']}): ssh {ssh_host} {shlex.quote(final_pve_cmd)}")
            else:
                print(f"Container {vmid} ({t['name']}): {final_pve_cmd}")
        return

    print(f"\nStarting execution of command: '{args.cmd}'")
    print("=" * 60)

    results = []
    for t in targets:
        vmid = t["vmid"]
        name = t["name"]
        node = t["node"]
        
        print(f"\n>>> [{vmid}] Updating {name} on node '{node}'...")
        
        # Build command structure
        container_cmd_str = f"/bin/sh -c {shlex.quote(args.cmd)}"
        pct_cmd = f"pct exec {vmid} -- {container_cmd_str}"
        if args.sudo:
            pct_cmd = f"sudo {pct_cmd}"
        
        if entrypoint_node and node != entrypoint_node:
            ssh_prefix = "sudo ssh" if args.sudo else "ssh"
            final_pve_cmd = f"{ssh_prefix} -o StrictHostKeyChecking=no root@{node} {shlex.quote(pct_cmd)}"
        else:
            final_pve_cmd = pct_cmd
            
        start_time = time.time()
        stdout, stderr, code = run_command(final_pve_cmd, ssh_host)
        elapsed = time.time() - start_time
        
        if code == 0:
            print(f"✓ [{vmid}] Success ({elapsed:.1f}s)")
            status_str = "SUCCESS"
        else:
            print(f"✗ [{vmid}] Failed with code {code} ({elapsed:.1f}s)")
            status_str = f"FAILED (Exit Code {code})"
            
        if stdout.strip():
            print("--- Output ---")
            print(stdout.strip())
        if stderr.strip():
            print("--- Error ---", file=sys.stderr)
            print(stderr.strip(), file=sys.stderr)
            
        results.append({
            "vmid": vmid,
            "name": name,
            "node": node,
            "status": status_str,
            "duration": f"{elapsed:.1f}s",
            "output": stdout,
            "error": stderr
        })
        print("-" * 60)

    # 4. Print final summary table
    print("\n" + "=" * 60)
    print("Execution Summary:")
    print("=" * 60)
    print(f"{'VMID':<8} {'Name':<20} {'Node':<10} {'Duration':<10} {'Result':<15}")
    print("-" * 60)
    for r in results:
        print(f"{r['vmid']:<8} {r['name']:<20} {r['node']:<10} {r['duration']:<10} {r['status']:<15}")
    print("=" * 60)

if __name__ == "__main__":
    main()
