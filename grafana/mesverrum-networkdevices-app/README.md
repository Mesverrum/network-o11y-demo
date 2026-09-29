# Network Devices

Devices the collectors are already polling. This is separate from the Instrumentation Hub discovery wizard.

Open a device to remove it or force a catalog profile onto that address. The profile list prefers the collector's own catalog: Alloy `discovery.snmp` serves
`GET …/fingerprints` and exports one series `discovery_snmp_library_info{fingerprinter,library_hash}`
(value = profile count). The hub Grafana proxies that HTTP for the lab canary
(`canary-http` → host `:12347`). If the collector is unreachable, the page falls back to
`src/profiles.json` from `scripts/build-profiles.py` (same hash algorithm) and warns.
Choosing a profile fills hot, cold, and topology module lists. Those lists stay editable.
Save writes one `discovery.snmp` override into the Fleet pipeline that already matches the
collector, then upserts it. The collector rescans when Fleet delivers the change. Custom
profiles in a customer's image appear when the catalog comes from that collector; the hash
is identity, not an allowlist.

A blank module list leaves that tier on the fingerprint. The collector does not treat an empty string as "turn this tier off."

Remove writes `ignore = true` for that address. Name and login are optional overrides. The login is an auth nickname from the collector's `SNMP_AUTHS` file, not a community string. Scrape intervals, CIDRs, and listeners stay on the hub pipeline.

The app calls the hub plugin's Fleet and stack proxies, so the hub plugin settings have to be filled in on the same Grafana.

Build on the colocated host, not the laptop:

```text
python3 local/scripts/devices-app-ship.py --e2e
```
