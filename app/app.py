# app.py

import ipaddress
import json
import time  # Added for sleeping
import os    # Added for environment variables

# Assuming 'delete' was a leftover and not used, otherwise it would need 'from requests.api import delete'
# from requests.api import delete
from termcolor import colored, cprint

from cloudflare import createDNSRecord, deleteDNSRecord, getZoneRecords, isValidDNSRecord, getZoneId
# getTailscaleDevice is conditionally imported later
from tailscale import isTailscaleIP, alterHostname # alterHostname is needed by headscale.py too
from config import getConfig

# import sys # sys was unused in the provided snippet

def perform_sync_cycle(): # Renamed from main()
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting DNS sync cycle...")
    config = getConfig()
    
    ts_records = [] # Initialize to ensure it's defined

    try:
        cf_ZoneId = getZoneId(config['cf-key'], config['cf-domain'])
        if not cf_ZoneId: # If getZoneId exits on error, this might not be hit, but good practice
            cprint(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Could not obtain Cloudflare Zone ID. Aborting sync cycle.", "red")
            return

        cf_records_current = getZoneRecords(config['cf-key'], config['cf-domain'], zoneId=cf_ZoneId)
        if cf_records_current is None: # If getZoneRecords exits on error or returns None
            cprint(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Could not obtain current Cloudflare records. Aborting sync cycle.", "red")
            return

        # Get records depending on mode
        if config['mode'] == "tailscale":
            from tailscale import getTailscaleDevice # Keep conditional import
            ts_records = getTailscaleDevice(config['ts-key'], config['ts-client-id'], config['ts-client-secret'], config['ts-tailnet'])
        elif config['mode'] == "headscale":
            from headscale import getHeadscaleDevice
            ts_records = getHeadscaleDevice(config['hs-apikey'], config['hs-baseurl'])
        else:
            cprint(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Invalid mode '{config.get('mode', 'None')}'. Aborting sync cycle.", "red")
            return

        if ts_records is None: # If getDevice functions return None on critical error
            cprint(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Failed to get records from {config['mode']}. Aborting sync cycle.", "red")
            return

        records_typemap = {
            4: 'A',
            6: 'AAAA'
        }

        print(colored(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Running in ","blue")+colored(config['mode'],"red"),colored("mode", "blue")+"\n")
        cprint(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Verifying/Adding DNS records:", "blue")

        # Prepare a list of FQDNs based on current ts_records for easier lookup
        current_ts_fqdns_ips = {}
        for ts_rec in ts_records:
            _sub = "." + config.get("cf-sub").lower() if config.get("cf-sub") else ""
            _hostname_part = alterHostname(ts_rec['hostname'].split('.')[0].lower()) # Apply prefix/postfix here
            _tsfqdn = _hostname_part + _sub + "." + config['cf-domain'].lower()
            current_ts_fqdns_ips[_tsfqdn + "_" + ts_rec['address']] = {'fqdn': _tsfqdn, 'address': ts_rec['address'], 'original_hostname': ts_rec['hostname']}


        for key, ts_detail in current_ts_fqdns_ips.items():
            tsfqdn = ts_detail['fqdn']
            ts_address = ts_detail['address']
            original_hostname = ts_detail['original_hostname'] # For isValidDNSRecord if it checks non-altered

            if any(c['name'].lower() == tsfqdn and c['content'] == ts_address for c in cf_records_current):
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{colored('UP-TO-DATE', 'green')}]: {tsfqdn} -> {ts_address}")
            else:
                ip = ipaddress.ip_address(ts_address)
                # isValidDNSRecord should ideally check the part that forms the subdomain, not the full FQDN.
                # The original script used ts_rec['hostname'] which is pre-alterHostname.
                if isValidDNSRecord(original_hostname):
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{colored('ADDING', 'yellow')}]: {tsfqdn} -> {ts_address}")
                    # createDNSRecord expects the non-prefixed/postfixed hostname for the 'name' param if subdomain is also passed
                    createDNSRecord(config['cf-key'], config['cf-domain'], original_hostname.split('.')[0].lower(), records_typemap[ip.version], ts_address, subdomain=config.get("cf-sub"), zoneId=cf_ZoneId)
                else:
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{colored('SKIPPING INVALID HOSTNAME', 'red')}]: Original hostname '{original_hostname}' for {tsfqdn} -> {ts_address}")

        cprint(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Cleaning up stale DNS records:", "blue")
        # Re-fetch Cloudflare records as they might have changed by the 'ADDING' step
        cf_records_for_cleanup = getZoneRecords(config['cf-key'], config['cf-domain'], zoneId=cf_ZoneId)
        if cf_records_for_cleanup is None:
            cprint(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Could not fetch Cloudflare records for cleanup. Skipping cleanup.", "red")
            return

        for cf_rec in cf_records_for_cleanup:
            cf_rec_fqdn = cf_rec['name'].lower()
            cf_rec_content = cf_rec['content']
            
            # Check if this Cloudflare record (FQDN + IP) is in our current Tailscale/Headscale list
            if (cf_rec_fqdn + "_" + cf_rec_content) in current_ts_fqdns_ips:
                # print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{colored('IN USE', 'green')}]: {cf_rec_fqdn} -> {cf_rec_content}")
                continue # This exact record (name and IP) is current and correct

            # If we reach here, the DNS record name+ip combo is not current.
            # Now check if the name *structure* matches what this script *would* manage
            # to avoid deleting unrelated records.
            expected_ending = (("." + config.get("cf-sub").lower() if config.get("cf-sub") else "") + "." + config['cf-domain'].lower())
            if not cf_rec_fqdn.endswith(expected_ending):
                continue # Not a record this script would manage (wrong subdomain/domain)

            # Extract the part of the hostname that would have been passed to alterHostname
            hostname_part_from_cf = cf_rec_fqdn[:-len(expected_ending)]
            # Remove prefix/postfix to see if the base matches an altered name
            # This is tricky if prefix/postfix themselves create ambiguity with other records.
            # The original logic was based on cf_name (pre-sub/domain part) matching prefix/postfix.
            
            # Simplified check: If it ends with the managed domain/subdomain AND has a Tailscale IP,
            # but isn't in the current_ts_fqdns_ips list (name+ip match), it's stale.
            if not isTailscaleIP(cf_rec_content):
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{colored('SKIP DELETE (Non-Tailscale IP)', 'magenta')}]: {cf_rec_fqdn} -> {cf_rec_content}")
                continue
            
            # If it looks like one of our records (based on domain/subdomain) and has a Tailscale IP
            # but does not match any current FQDN+IP combo from Headscale, then it's stale.
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{colored('DELETING STALE', 'yellow')}]: {cf_rec_fqdn} -> {cf_rec_content}")
            deleteDNSRecord(config['cf-key'], config['cf-domain'], cf_rec['id'], zoneId=cf_ZoneId)

    except requests.exceptions.RequestException as e: # Catch network errors for API calls
        cprint(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Network error during sync cycle: {e}", "red")
    except KeyError as e: # Catch missing keys in expected data
        cprint(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Configuration or API response error (missing key): {e}", "red")
    except Exception as e: # Catch any other unexpected error during the sync cycle
        cprint(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: An unexpected error occurred: {e}", "red")
        import traceback
        traceback.print_exc() # Print full traceback for unexpected errors

if __name__ == '__main__':
    sync_interval_minutes_str = os.environ.get('SYNC_INTERVAL_MINUTES', '15') # Default to 15 minutes
    try:
        sync_interval_minutes = int(sync_interval_minutes_str)
        if sync_interval_minutes <= 0:
            print(colored(f"Warning: SYNC_INTERVAL_MINUTES must be positive. Using default 15 minutes.", "yellow"))
            sync_interval_minutes = 15
    except ValueError:
        print(colored(f"Warning: Invalid SYNC_INTERVAL_MINUTES value '{sync_interval_minutes_str}'. Using default 15 minutes.", "yellow"))
        sync_interval_minutes = 15

    sync_interval_seconds = sync_interval_minutes * 60
    cprint(f"DNS Sync script started. Sync interval: {sync_interval_minutes} minutes.", "green")

    while True:
        perform_sync_cycle() # Call the main sync logic
        cprint(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Sync cycle finished. Sleeping for {sync_interval_minutes} minutes...", "blue")
        time.sleep(sync_interval_seconds)
