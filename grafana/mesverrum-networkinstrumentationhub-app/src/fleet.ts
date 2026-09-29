import { getBackendSrv } from '@grafana/runtime';
import { lastValueFrom } from 'rxjs';
import pluginJson from './plugin.json';

const STORE = 'hub.';

export type Collector = {
  id: string;
  enabled?: boolean;
  attributes?: Record<string, string>;
};

export type FleetPipeline = {
  id?: string;
  name?: string;
  enabled?: boolean;
  matchers?: string[];
};

export type GroupDraft = {
  collectorId: string;
  name: string;
  description: string;
  cidrs: string[];
  auths: string[];
};

export function readDraft(): GroupDraft {
  return {
    collectorId: sessionStorage.getItem(STORE + 'collectorId') || 'hub-canary',
    name: sessionStorage.getItem(STORE + 'name') || 'hub-demo',
    description: sessionStorage.getItem(STORE + 'description') || 'Instrumentation Hub canary',
    cidrs: (sessionStorage.getItem(STORE + 'cidrs') || '172.20.20.0/24').split('\n').filter(Boolean),
    auths: readAuths(),
  };
}

function readAuths(): string[] {
  const saved = sessionStorage.getItem(STORE + 'auths');
  const raw = saved == null ? sessionStorage.getItem(STORE + 'auth') || 'public_v2' : saved;
  return raw
    .split(/[\s,]+/)
    .map((name) => name.trim())
    .filter(Boolean);
}

export function writeDraft(draft: GroupDraft) {
  sessionStorage.setItem(STORE + 'collectorId', draft.collectorId);
  sessionStorage.setItem(STORE + 'name', draft.name);
  sessionStorage.setItem(STORE + 'description', draft.description);
  sessionStorage.setItem(STORE + 'cidrs', draft.cidrs.join('\n'));
  sessionStorage.setItem(STORE + 'auths', draft.auths.join('\n'));
}

export type CollectChoices = {
  neighbors: boolean;
  traps: boolean;
  syslog: boolean;
  netflow: boolean;
  sflow: boolean;
  rescan: boolean;
};

function flag(key: string, fallback: boolean): boolean {
  const value = sessionStorage.getItem(STORE + key);
  return value == null ? fallback : value === '1';
}

export function readChoices(): CollectChoices {
  return {
    neighbors: flag('neighbors', true),
    traps: flag('traps', true),
    syslog: flag('syslog', true),
    netflow: flag('netflow', false),
    sflow: flag('sflow', false),
    rescan: flag('rescan', true),
  };
}

export function writeChoices(choices: CollectChoices) {
  sessionStorage.setItem(STORE + 'neighbors', choices.neighbors ? '1' : '0');
  sessionStorage.setItem(STORE + 'traps', choices.traps ? '1' : '0');
  sessionStorage.setItem(STORE + 'syslog', choices.syslog ? '1' : '0');
  sessionStorage.setItem(STORE + 'netflow', choices.netflow ? '1' : '0');
  sessionStorage.setItem(STORE + 'sflow', choices.sflow ? '1' : '0');
  sessionStorage.setItem(STORE + 'rescan', choices.rescan ? '1' : '0');
}

export function markApplied(name: string) {
  sessionStorage.setItem(STORE + 'applied', name);
}

export function markDiscovery(name: string) {
  sessionStorage.setItem(STORE + 'discovery', name);
}

export function discoveryName(): string {
  return sessionStorage.getItem(STORE + 'discovery') || '';
}

export function appliedName(): string {
  return sessionStorage.getItem(STORE + 'applied') || '';
}

export async function fleetCall<T>(rpc: string, body: unknown): Promise<T> {
  const response = await lastValueFrom(
    getBackendSrv().fetch<T>({
      url: `/api/plugin-proxy/${pluginJson.id}/fleet/${rpc}`,
      method: 'POST',
      data: body,
      showErrorAlert: false,
    })
  );
  return response.data;
}

export const FLEET_URL = 'https://fleet-management-prod-008.grafana.net';
export const NETWORK_ALLOY_IMAGE = 'srl-local/alloy:network-dev';
export const INSTALL_ID = '__install__';

export async function readStackId(): Promise<string> {
  const settings = await getBackendSrv().get<{ jsonData?: { stackId?: string } }>(
    `/api/plugins/${pluginJson.id}/settings`
  );
  return settings.jsonData?.stackId || '';
}

export function validateCollectorName(name: string): string | null {
  if (!/^[a-z][a-z0-9-]{1,62}$/.test(name)) {
    return 'Use lowercase letters, numbers, and -. Start with a letter.';
  }
  return null;
}

/** The role keeps a hub-installed collector out of pipelines matched to role="network-snmp". */
export function installCommand(name: string, stackId: string): string {
  return `mkdir -p ~/${name} && cd ~/${name}

cat > config.alloy <<'EOF'
remotecfg {
  url            = "${FLEET_URL}"
  id             = "${name}"
  name           = "${name}"
  poll_frequency = "30s"

  basic_auth {
    username = "${stackId || '<stack id>'}"
    password = env("GC_FM_TOKEN")
  }

  attributes = {
    "role" = "hub-collector",
  }
}
EOF

docker run -d --name ${name} --restart unless-stopped \\
  --network host --cap-add NET_RAW \\
  -e GC_FM_TOKEN='<fleet token>' \\
  -e GC_OTLP_URL='<otlp url>' -e GC_OTLP_ACCOUNT='${stackId || '<stack id>'}' -e GC_OTLP_KEY='<otlp token>' \\
  -e SNMP_AUTHS="$(cat snmp-auths.yml)" \\
  -v "$PWD/config.alloy:/etc/alloy/config.alloy:ro" \\
  ${NETWORK_ALLOY_IMAGE} \\
  run /etc/alloy/config.alloy --storage.path=/var/lib/alloy/data \\
  --server.http.listen-addr=0.0.0.0:12348 --stability.level=experimental`;
}

function alloyString(value: string): string {
  return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

const NAME_RE = /^[A-Za-z][A-Za-z0-9_-]{0,62}$/;
const CIDR_RE = /^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/;

export function parseRanges(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((part) => part.trim())
    .filter(Boolean);
}

export function validateGroupName(name: string): string | null {
  if (!name) {
    return 'Give the group a name.';
  }
  if (!NAME_RE.test(name)) {
    return 'Start with a letter. Use only letters, numbers, _ and -.';
  }
  return null;
}

export function validateAuthName(auth: string): string | null {
  if (!auth) {
    return 'Enter the login nickname.';
  }
  if (!NAME_RE.test(auth)) {
    return 'Start with a letter. Use only letters, numbers, _ and -.';
  }
  return null;
}

export function validateAuths(auths: string[]): string | null {
  if (auths.length === 0) {
    return 'Add at least one login nickname.';
  }
  const seen = new Set<string>();
  for (const auth of auths) {
    const problem = validateAuthName(auth);
    if (problem) {
      return `${auth}: ${problem}`;
    }
    if (seen.has(auth)) {
      return `${auth} is listed twice.`;
    }
    seen.add(auth);
  }
  return null;
}

export function validateNote(note: string): string | null {
  if (note.length > 256 || /[\r\n]/.test(note)) {
    return 'One line, 256 characters or fewer.';
  }
  return null;
}

export function validateRanges(cidrs: string[]): string | null {
  if (cidrs.length === 0) {
    return 'Add at least one range.';
  }
  for (const cidr of cidrs) {
    if (!CIDR_RE.test(cidr)) {
      return `${cidr} is not an IPv4 CIDR. Example: 172.20.20.0/24.`;
    }
  }
  return null;
}

export function validateDraft(draft: GroupDraft): string | null {
  return (
    validateGroupName(draft.name) ||
    validateAuths(draft.auths) ||
    validateNote(draft.description) ||
    validateRanges(draft.cidrs) ||
    (draft.collectorId ? null : 'Pick a collector first.')
  );
}

export function pipelineName(groupName: string): string {
  // Fleet stores the pipeline name as an Alloy identifier, so hyphens are not allowed.
  return `hub_${groupName.replace(/[^A-Za-z0-9_]/g, '_')}`;
}

export function refreshInterval(rescan: boolean): string {
  // discovery.snmp has no run-once flag. A year is long enough that the scan does not repeat until someone edits refresh_interval.
  return rescan ? '24h' : '8760h';
}

function discoveryBlock(draft: GroupDraft, choices: CollectChoices): string {
  const cidrs = draft.cidrs.map(alloyString).join(', ');
  return `discovery.snmp "hub" {
  refresh_interval = "${refreshInterval(choices.rescan)}"
  state_path       = "/var/lib/alloy/data/hub-discovery.state.json"
  auths            = env("SNMP_AUTHS")

  group {
    name        = ${alloyString(draft.name)}
    description = ${alloyString(draft.description)}
    cidrs       = [${cidrs}]
    auths       = [${draft.auths.map(alloyString).join(', ')}]
  }
}`;
}

function exportTail(collector: string): string {
  return `otelcol.receiver.prometheus "hub" {
  output {
    metrics = [otelcol.processor.batch.hub.input]
  }
}

prometheus.exporter.self "hub" { }

prometheus.relabel "hub_self" {
  forward_to = [otelcol.receiver.prometheus.hub.receiver]

  rule {
    target_label = "job"
    replacement  = "alloy"
  }

  rule {
    target_label = "collector"
    replacement  = ${collector}
  }

  rule {
    source_labels = ["__name__"]
    regex         = "discovery_snmp_device_info|discovery_snmp_group_info"
    action        = "keep"
  }
}

prometheus.scrape "hub_self" {
  targets         = prometheus.exporter.self.hub.targets
  scrape_interval = "30s"
  forward_to      = [prometheus.relabel.hub_self.receiver]
}

otelcol.processor.batch "hub" {
  output {
    metrics = [otelcol.exporter.otlphttp.hub.input]
  }
}

otelcol.auth.basic "hub" {
  username = env("GC_OTLP_ACCOUNT")
  password = env("GC_OTLP_KEY")
}

otelcol.exporter.otlphttp "hub" {
  client {
    endpoint = env("GC_OTLP_URL")
    auth     = otelcol.auth.basic.hub.handler
  }
}`;
}

/** Discovery sweep only. Device polling is added later by pipelineRiver. */
export function discoveryRiver(draft: GroupDraft, choices: CollectChoices = readChoices()): string {
  const collector = alloyString(draft.collectorId);
  return `// Discovery only. Written by the Network Instrumentation Hub for ${draft.collectorId}.
${discoveryBlock(draft, choices)}

${exportTail(collector)}
`;
}

/** River fragment Fleet will deliver to the one collector this group is matched to. */
export function pipelineRiver(draft: GroupDraft, choices: CollectChoices = readChoices()): string {
  const collector = alloyString(draft.collectorId);
  return `// Written by the Network Instrumentation Hub. Matched only to ${draft.collectorId}.
${discoveryBlock(draft, choices)}

${tierScrape('hot', '60s', '55s', collector)}

${tierScrape('cold', '5m', '4m', collector)}
${choices.neighbors ? `\n${topologyBlock()}\n` : ''}
${exportTail(collector)}
`;
}

// Neighbor walks stay on the collector. prometheus.network_topology reconciles them
// and forwards only network_topology_device_info and network_topology_edge_info.
function topologyBlock(): string {
  return `// Neighbor topology. Requires an Alloy image that includes prometheus.network_topology.
discovery.relabel "hub_topology" {
  targets = discovery.snmp.hub.targets

  rule {
    source_labels = ["snmp_tier"]
    regex         = "topology"
    action        = "keep"
  }
}

prometheus.exporter.snmp "hub_topology" {
  auths   = env("SNMP_AUTHS")
  targets = discovery.relabel.hub_topology.output
}

prometheus.scrape "hub_topology" {
  targets         = prometheus.exporter.snmp.hub_topology.targets
  scrape_interval = "15m"
  scrape_timeout  = "2m"
  forward_to      = [prometheus.network_topology.hub.receiver]
}

prometheus.network_topology "hub" {
  stale_after = "30m"
  forward_to  = [otelcol.receiver.prometheus.hub.receiver]
}`;
}

function tierScrape(tier: 'hot' | 'cold', interval: string, timeout: string, collector: string): string {
  const id = `hub_${tier}`;
  return `discovery.relabel "${id}" {
  targets = discovery.snmp.hub.targets

  rule {
    source_labels = ["snmp_tier"]
    regex         = "${tier}"
    action        = "keep"
  }
}

prometheus.exporter.snmp "${id}" {
  auths   = env("SNMP_AUTHS")
  targets = discovery.relabel.${id}.output
}

prometheus.relabel "${id}" {
  forward_to = [otelcol.receiver.prometheus.hub.receiver]

  rule {
    target_label = "job"
    replacement  = "alloy-snmp"
  }

  rule {
    target_label = "collector"
    replacement  = ${collector}
  }
}

prometheus.scrape "${id}" {
  targets         = prometheus.exporter.snmp.${id}.targets
  scrape_interval = "${interval}"
  scrape_timeout  = "${timeout}"
  forward_to      = [prometheus.relabel.${id}.receiver]
}`;
}

export async function upsertPipeline(draft: GroupDraft, contents: string): Promise<string> {
  const name = pipelineName(draft.name);
  await fleetCall('pipeline.v1.PipelineService/UpsertPipeline', {
    pipeline: {
      name,
      contents,
      matchers: [`collector.ID="${draft.collectorId}"`],
      enabled: true,
    },
  });
  return name;
}

export type FoundDevice = {
  name: string;
  address: string;
  auth: string;
  sysObjectID: string;
};

type PromQuery = {
  data?: { result?: Array<{ metric?: Record<string, string> }> };
};

export async function queryFoundDevices(group: string): Promise<FoundDevice[]> {
  const response = await lastValueFrom(
    getBackendSrv().fetch<PromQuery>({
      url: `/api/plugin-proxy/${pluginJson.id}/stack/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query`,
      method: 'GET',
      params: { query: `discovery_snmp_device_info{group="${group}"}` },
      showErrorAlert: false,
    })
  );
  const rows = response.data?.data?.result || [];
  return rows
    .map((row) => ({
      name: row.metric?.device_name || '',
      address: row.metric?.address || '',
      auth: row.metric?.auth || '',
      sysObjectID: row.metric?.sysObjectID || '',
    }))
    .filter((device) => device.name || device.address)
    .sort((a, b) => a.name.localeCompare(b.name));
}
