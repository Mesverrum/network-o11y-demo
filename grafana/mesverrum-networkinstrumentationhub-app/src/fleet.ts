import { getBackendSrv } from '@grafana/runtime';
import { lastValueFrom } from 'rxjs';
import { preserveProfileOverrides } from './deviceOverrides';
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
  ignores: string[];
};

// Offset from the lab collector on the same host (1620/11620, 1514/1515, 2055, 6343/6344)
// so this Alloy can bind without taking those sockets.
export const LISTEN = {
  traps: 11621,
  syslog: 1516,
  netflow: 2056,
  sflow: 6345,
} as const;

export function readDraft(): GroupDraft {
  return {
    collectorId: sessionStorage.getItem(STORE + 'collectorId') || 'hub-canary',
    name: sessionStorage.getItem(STORE + 'name') || 'hub-demo',
    description: sessionStorage.getItem(STORE + 'description') || 'Instrumentation Hub canary',
    cidrs: (sessionStorage.getItem(STORE + 'cidrs') || '172.20.20.0/24').split('\n').filter(Boolean),
    auths: readAuths(),
    ignores: readIgnores(),
  };
}

function readIgnores(): string[] {
  return (sessionStorage.getItem(STORE + 'ignores') || '')
    .split(/[\s,]+/)
    .map((ip) => ip.trim())
    .filter(Boolean)
    .sort();
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
  sessionStorage.setItem(STORE + 'ignores', [...draft.ignores].sort().join('\n'));
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

export function markApplied(name: string, revision: string) {
  sessionStorage.setItem(STORE + 'applied', name);
  sessionStorage.setItem(STORE + 'appliedRevision', revision);
  sessionStorage.setItem(STORE + 'appliedAt', String(Date.now()));
}

export function appliedRevision(): { revision: string; at: number } {
  return {
    revision: sessionStorage.getItem(STORE + 'appliedRevision') || '',
    at: Number(sessionStorage.getItem(STORE + 'appliedAt') || 0),
  };
}

const REVISION_SLOT = '__HUB_REVISION__';

/** FNV-1a over the pipeline text. The collector echoes it back as hub_revision. */
function revisionOf(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, '0');
}

function stampRevision(river: string): string {
  return river.split(REVISION_SLOT).join(revisionOf(river));
}

export function riverRevision(river: string): string {
  const m = river.match(/target_label = "hub_revision"\s+replacement\s+= "([0-9a-f]{8})"/);
  return m ? m[1] : '';
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

const IPV4_RE = /^\d{1,3}(\.\d{1,3}){3}$/;

export function validateAddress(address: string): string | null {
  if (!IPV4_RE.test(address)) {
    return `${address} is not an IPv4 address.`;
  }
  return null;
}

function discoveryBlock(draft: GroupDraft, choices: CollectChoices): string {
  const cidrs = draft.cidrs.map(alloyString).join(', ');
  const ignores = [...draft.ignores].filter((ip) => !validateAddress(ip)).sort();
  const overrides = ignores
    .map(
      (ip) => `  override {
    address = ${alloyString(ip)}
    ignore  = true
  }`
    )
    .join('\n');
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
${overrides}
}`;
}

// Stock Fleet self-monitoring may not reach this stack, so the hub pipeline ships the
// signals its dashboards and Receiving page read: remote config, component health, discovery.
const SELF_METRICS = [
  'discovery_snmp_.*',
  'remotecfg_last_load_successful',
  'remotecfg_last_load_success_timestamp_seconds',
  'remotecfg_load_attempts_total',
  'remotecfg_load_failures_total',
  'remotecfg_hash',
  'alloy_component_controller_running_components',
  'alloy_config_last_load_successful',
  'alloy_build_info',
].join('|');

function exportTail(collector: string, logs: boolean): string {
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
    target_label = "hub_revision"
    replacement  = "${REVISION_SLOT}"
  }

  rule {
    source_labels = ["__name__"]
    regex         = "${SELF_METRICS}|otelcol_receiver_accepted_log_records_total|otelcol_receiver_refused_log_records_total"
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
${logs ? '    logs    = [otelcol.exporter.otlphttp.hub.input]\n' : ''}  }
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
  return stampRevision(`// Discovery only. Written by the Network Instrumentation Hub for ${draft.collectorId}.
${discoveryBlock(draft, choices)}

${exportTail(collector, false)}
`);
}

/** River fragment Fleet will deliver to the one collector this group is matched to. */
export function pipelineRiver(draft: GroupDraft, choices: CollectChoices = readChoices()): string {
  const collector = alloyString(draft.collectorId);
  const logs = choices.traps || choices.syslog;
  return stampRevision(`// Written by the Network Instrumentation Hub. Matched only to ${draft.collectorId}.
${discoveryBlock(draft, choices)}

${tierScrape('hot', '60s', '55s', collector)}

${tierScrape('cold', '5m', '4m', collector)}
${choices.neighbors ? `\n${topologyBlock(collector)}\n` : ''}
${listenersBlock(choices, collector)}
${exportTail(collector, logs)}
`);
}

/** Upsert whichever pipeline this browser has reached, so an ignore does not wipe polling. */
export async function pushDraft(draft: GroupDraft, choices: CollectChoices): Promise<string> {
  let river = appliedName() ? pipelineRiver(draft, choices) : discoveryRiver(draft, choices);
  try {
    const listed = await fleetCall<{ pipelines?: Array<{ name?: string; contents?: string }> }>(
      'pipeline.v1.PipelineService/ListPipelines',
      {}
    );
    const current = (listed.pipelines || []).find((item) => item.name === pipelineName(draft.name));
    if (current?.contents) {
      river = preserveProfileOverrides(river, current.contents, draft.ignores);
    }
  } catch {
    // First write, or Fleet list failed. The draft still upserts.
  }
  const name = await upsertPipeline(draft, river);
  if (appliedName()) {
    markApplied(name, riverRevision(river));
  } else {
    markDiscovery(name);
  }
  return name;
}

const otel = (statement: string) => '`' + statement + '`';

function listenersBlock(choices: CollectChoices, collector: string): string {
  const any = choices.traps || choices.syslog || choices.netflow || choices.sflow;
  if (!any) {
    return '';
  }
  const setService = (name: string) => otel('set(attributes["service.name"], "' + name + '")');
  const setCollector = otel('set(attributes["collector"], ' + collector + ')');
  const setLocal = otel(
    'set(attributes["network.local.address"], attributes["source.address"]) where attributes["source.address"] != nil'
  );
  const setPeer = otel(
    'set(attributes["network.peer.address"], attributes["destination.address"]) where attributes["destination.address"] != nil'
  );
  const setIntegration = otel('set(datapoint.attributes["integration"], "alloy-netflow")');
  const parts = [
    `// Listeners. Ports are offset from the lab collector so both can bind on one host.
discovery.relabel "hub_join" {
  targets = discovery.snmp.hub.targets

  rule {
    source_labels = ["snmp_tier"]
    regex         = "hot"
    action        = "keep"
  }
}`,
  ];
  if (choices.traps) {
    parts.push(`otelcol.receiver.snmptrap "hub_traps" {
  listen_address = "0.0.0.0:${LISTEN.traps}"
  targets        = discovery.relabel.hub_join.output

  attributes = {
    job       = "snmptrap",
    collector = ${collector},
  }

  output {
    logs = [otelcol.processor.transform.hub_traps.input]
  }
}

otelcol.processor.transform "hub_traps" {
  error_mode = "ignore"

  log_statements {
    context = "resource"
    statements = [
      ${setService('alloy-snmptrap')},
      ${setCollector},
    ]
  }

  output {
    logs = [otelcol.processor.batch.hub.input]
  }
}`);
  }
  if (choices.syslog) {
    parts.push(`otelcol.receiver.syslog "hub_syslog" {
  protocol              = "none"
  allow_skip_pri_header = true
  on_error              = "send"
  targets               = discovery.relabel.hub_join.output

  udp {
    listen_address = "0.0.0.0:${LISTEN.syslog}"
    add_attributes = true
  }

  output {
    logs = [otelcol.processor.transform.hub_syslog.input]
  }
}

otelcol.processor.transform "hub_syslog" {
  error_mode = "ignore"

  log_statements {
    context = "resource"
    statements = [
      ${setService('alloy-syslog')},
      ${setCollector},
    ]
  }

  output {
    logs = [otelcol.processor.batch.hub.input]
  }
}`);
  }
  if (choices.netflow || choices.sflow) {
    const receivers: string[] = [];
    if (choices.netflow) {
      receivers.push(`otelcol.receiver.netflow "hub_netflow" {
  scheme              = "netflow"
  hostname            = "0.0.0.0"
  port                = ${LISTEN.netflow}
  targets             = discovery.relabel.hub_join.output
  udp_host_cache_size = 1024

  output {
    logs = [otelcol.processor.transform.hub_flow.input]
  }
}`);
    }
    if (choices.sflow) {
      receivers.push(`otelcol.receiver.netflow "hub_sflow" {
  scheme              = "sflow"
  hostname            = "0.0.0.0"
  port                = ${LISTEN.sflow}
  targets             = discovery.relabel.hub_join.output
  udp_host_cache_size = 1024

  output {
    logs = [otelcol.processor.transform.hub_flow.input]
  }
}`);
    }
    parts.push(`${receivers.join('\n\n')}

otelcol.processor.transform "hub_flow" {
  error_mode = "ignore"

  log_statements {
    context = "resource"
    statements = [
      ${setService('alloy-netflow')},
      ${setCollector},
    ]
  }

  log_statements {
    context = "log"
    statements = [
      ${setLocal},
      ${setPeer},
    ]
  }

  output {
    logs = [otelcol.connector.signaltometrics.hub_flow.input]
  }
}

otelcol.connector.signaltometrics "hub_flow" {
  error_mode = "ignore"

  logs {
    name        = "alloy.network.io.by_flow"
    description = "Bytes observed in decoded NetFlow, IPFIX, and sFlow records"
    unit        = "By"
    include_resource_attributes {
      key = "service.name"
    }
    include_resource_attributes {
      key = "collector"
    }
    attributes {
      key = "flow.sampler_address"
    }
    attributes {
      key = "network.local.address"
      optional = true
    }
    attributes {
      key = "network.peer.address"
      optional = true
    }
    attributes {
      key = "device_name"
      optional = true
    }
    sum { value = "Int(attributes[\\"flow.io.bytes\\"])" }
  }

  output {
    metrics = [otelcol.processor.deltatocumulative.hub_flow.input]
  }
}

otelcol.processor.deltatocumulative "hub_flow" {
  max_stale   = "5m"
  max_streams = 100000

  output {
    metrics = [otelcol.processor.transform.hub_flow_metrics.input]
  }
}

otelcol.processor.transform "hub_flow_metrics" {
  error_mode = "ignore"

  metric_statements {
    context = "datapoint"
    statements = [
      ${setIntegration},
    ]
  }

  output {
    metrics = [otelcol.processor.batch.hub.input]
  }
}`);
  }
  return parts.join('\n\n') + '\n';
}

// Neighbor walks stay on the collector. prometheus.network_topology reconciles them
// and forwards only network_topology_device_info and network_topology_edge_info.
function topologyBlock(collector: string): string {
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
  forward_to  = [prometheus.relabel.hub_topology.receiver]
}

prometheus.relabel "hub_topology" {
  forward_to = [otelcol.receiver.prometheus.hub.receiver]

  rule {
    target_label = "collector"
    replacement  = ${collector}
  }
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

  rule {
    target_label = "snmp_tier"
    replacement  = "${tier}"
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

type PromSample = { metric?: Record<string, string>; value?: [number, string] };

type PromQuery = {
  data?: { result?: PromSample[] };
};

function promLabel(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
}

/** Instant query against the stack the hub collector exports to. */
export async function promQuery(expr: string): Promise<PromSample[]> {
  const response = await lastValueFrom(
    getBackendSrv().fetch<PromQuery>({
      url: `/api/plugin-proxy/${pluginJson.id}/stack/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query`,
      method: 'GET',
      params: { query: expr },
      showErrorAlert: false,
    })
  );
  return response.data?.data?.result || [];
}

async function promScalar(expr: string): Promise<number | null> {
  const rows = await promQuery(expr);
  if (rows.length === 0 || !rows[0].value) {
    return null;
  }
  const n = Number(rows[0].value[1]);
  return Number.isFinite(n) ? n : null;
}

export type CheckState = 'ok' | 'waiting' | 'problem' | 'off';

export type LiveCheck = {
  id: string;
  label: string;
  state: CheckState;
  detail: string;
  dashboard: string;
};

export const DASHBOARDS = {
  rollout: 'hub-fleet-rollout',
  discovery: 'hub-discovery',
  arriving: 'hub-data-arriving',
};

export function dashboardUrl(uid: string, draft: GroupDraft): string {
  const q = new URLSearchParams({
    'var-collector': draft.collectorId,
    'var-group': draft.name,
    'var-pipeline': pipelineName(draft.name),
  });
  return `/d/${uid}?${q.toString()}`;
}

function ago(seconds: number): string {
  if (seconds < 90) {
    return `${Math.round(seconds)}s ago`;
  }
  if (seconds < 5400) {
    return `${Math.round(seconds / 60)}m ago`;
  }
  return `${Math.round(seconds / 3600)}h ago`;
}

/** Each check reads the metrics the hub pipeline itself ships, filtered to this collector. */
export async function liveChecks(draft: GroupDraft, choices: CollectChoices): Promise<LiveCheck[]> {
  const c = `collector="${promLabel(draft.collectorId)}"`;
  const g = `group="${promLabel(draft.name)}"`;
  const controller = `controller_id="${promLabel(pipelineName(draft.name))}.default"`;
  const expected = appliedRevision();
  const want = expected.revision || riverRevision(pipelineRiver(draft, choices));
  const [running, loaded, polled, failures, healthy, unhealthy, devices, groupInfo, hotUp, hotAll, coldUp, coldAll, coldAge, edges, trapsIn, syslogIn, netflowIn, sflowIn, flowSeries] =
    await Promise.all([
      promQuery(`count by (hub_revision) (discovery_snmp_group_info{${c},${g}})`),
      promScalar(`max(remotecfg_last_load_successful{${c}})`),
      promScalar(`sum(increase(remotecfg_load_attempts_total{${c}}[5m]))`),
      promScalar(`sum(increase(remotecfg_load_failures_total{${c}}[15m]))`),
      promScalar(`sum(alloy_component_controller_running_components{${c},${controller},health_type="healthy"})`),
      promScalar(
        `sum(alloy_component_controller_running_components{${c},${controller},health_type!="healthy"}) or vector(0)`
      ),
      promScalar(`count(count by (device_name, address) (discovery_snmp_device_info{${c},${g}})) or vector(0)`),
      promScalar(`count(count by (group) (discovery_snmp_group_info{${c},${g}})) or vector(0)`),
      promScalar(`sum(up{job="alloy-snmp",${c},snmp_tier="hot"}) or vector(0)`),
      promScalar(`count(up{job="alloy-snmp",${c},snmp_tier="hot"}) or vector(0)`),
      promScalar(`sum(up{job="alloy-snmp",${c},snmp_tier="cold"}) or vector(0)`),
      promScalar(`count(up{job="alloy-snmp",${c},snmp_tier="cold"}) or vector(0)`),
      promScalar(`time() - max(timestamp(snmp_ifInErrors{job="alloy-snmp",${c}}))`),
      promScalar(`count(network_topology_edge_info{${c}}) or vector(0)`),
      promScalar(`sum(increase(otelcol_receiver_accepted_log_records_total{${c},receiver=~".*hub_traps.*"}[15m]))`),
      promScalar(`sum(increase(otelcol_receiver_accepted_log_records_total{${c},receiver=~".*hub_syslog.*"}[15m]))`),
      promScalar(`sum(increase(otelcol_receiver_accepted_log_records_total{${c},receiver=~".*hub_netflow.*"}[15m]))`),
      promScalar(`sum(increase(otelcol_receiver_accepted_log_records_total{${c},receiver=~".*hub_sflow.*"}[15m]))`),
      promScalar(`count(alloy_network_io_by_flow_bytes{${c},integration="alloy-netflow"})`),
    ]);

  const revisions = running.map((row) => row.metric?.hub_revision || 'an older unstamped pipeline');
  const sinceApply = expected.at ? (Date.now() - expected.at) / 1000 : Infinity;
  const polls =
    loaded === null
      ? ''
      : ` Last Fleet load ${loaded === 1 ? 'succeeded' : 'failed'}; ${Math.round(polled ?? 0)} polls in 5m.` +
        (failures ? ` ${Math.round(failures)} failed loads in 15m.` : '');
  let remotecfg: Pick<LiveCheck, 'state' | 'detail'>;
  if (revisions.includes(want)) {
    remotecfg = { state: 'ok', detail: `Running revision ${want}, the one applied.${polls}` };
  } else if (revisions.length === 0) {
    remotecfg = {
      state: 'waiting',
      detail: `Nothing from ${draft.collectorId} for ${draft.name} yet. It shows about a minute after Apply.`,
    };
  } else if (sinceApply < 180) {
    remotecfg = {
      state: 'waiting',
      detail: `Still on revision ${revisions.join(', ')}. Waiting for ${want} to load.${polls}`,
    };
  } else {
    remotecfg = {
      state: 'problem',
      detail:
        `Fleet has revision ${want} but ${draft.collectorId} is still running ${revisions.join(', ')}. ` +
        'The collector rejected the new pipeline and kept the last one. Its log line is ' +
        '"failed to parse and load new remote configuration".' +
        polls,
    };
  }

  const checks: LiveCheck[] = [];
  checks.push({ id: 'remotecfg', label: 'Collector took the config', dashboard: DASHBOARDS.rollout, ...remotecfg });
  checks.push({
    id: 'components',
    label: 'Pipeline components healthy',
    state: healthy === null ? 'waiting' : (unhealthy ?? 0) > 0 ? 'problem' : 'ok',
    detail:
      healthy === null
        ? `${pipelineName(draft.name)} is not running on ${draft.collectorId} yet.`
        : `${healthy} healthy, ${unhealthy ?? 0} unhealthy in ${pipelineName(draft.name)}.`,
    dashboard: DASHBOARDS.rollout,
  });
  checks.push({
    id: 'discovery',
    label: 'Discovery found devices',
    state: !groupInfo ? 'waiting' : devices ? 'ok' : 'problem',
    detail: !groupInfo
      ? `Group ${draft.name} has not reported yet.`
      : devices
      ? `${devices} devices answered in ${draft.name}.`
      : `Group ${draft.name} is scanning ${draft.cidrs.join(', ')} but nothing answered. Check the ranges and logins.`,
    dashboard: DASHBOARDS.discovery,
  });
  checks.push({
    id: 'hot',
    label: 'Health and traffic (every minute)',
    state: !hotAll ? 'waiting' : hotUp === hotAll ? 'ok' : 'problem',
    detail: !hotAll ? 'No health polls yet.' : `${hotUp} of ${hotAll} devices answered the last poll.`,
    dashboard: DASHBOARDS.arriving,
  });
  checks.push({
    id: 'cold',
    label: 'Names and errors (every 5 minutes)',
    state: !coldAll || coldAge === null ? 'waiting' : coldAge < 900 && coldUp === coldAll ? 'ok' : 'problem',
    detail:
      !coldAll || coldAge === null
        ? 'No 5-minute poll yet. The first one lands within 5 minutes.'
        : `${coldUp} of ${coldAll} devices answered. Last sample ${ago(coldAge)}.`,
    dashboard: DASHBOARDS.arriving,
  });
  checks.push({
    id: 'topology',
    label: 'Neighbor topology',
    state: !choices.neighbors ? 'off' : edges ? 'ok' : 'waiting',
    detail: !choices.neighbors
      ? 'Off'
      : edges
      ? `${edges} neighbor links.`
      : 'Neighbor walks run every 15 minutes. The first links show after that.',
    dashboard: DASHBOARDS.arriving,
  });
  const listener = (id: string, label: string, on: boolean, port: number, accepted: number | null, extra: number | null): LiveCheck => {
    if (!on) {
      return { id, label, state: 'off', detail: 'Off', dashboard: DASHBOARDS.arriving };
    }
    const arrived = (accepted ?? 0) > 0 || (extra ?? 0) > 0;
    if (arrived) {
      const bits = [`UDP ${port}`];
      if ((accepted ?? 0) > 0) {
        bits.push(`${Math.round(accepted ?? 0)} records in 15m`);
      }
      if ((extra ?? 0) > 0) {
        bits.push(`${extra} flow series`);
      }
      return { id, label, state: 'ok', detail: bits.join('. ') + '.', dashboard: DASHBOARDS.arriving };
    }
    if ((unhealthy ?? 0) > 0 && accepted === null) {
      return {
        id,
        label,
        state: 'problem',
        detail: `Nothing on UDP ${port}, and the pipeline has an unhealthy component. A port already in use fails the bind.`,
        dashboard: DASHBOARDS.arriving,
      };
    }
    return {
      id,
      label,
      state: 'waiting',
      detail: `Listening on UDP ${port}. Nothing received yet. Point the device at ${draft.collectorId}.`,
      dashboard: DASHBOARDS.arriving,
    };
  };
  checks.push(listener('traps', 'Alarms (SNMP traps)', choices.traps, LISTEN.traps, trapsIn, null));
  checks.push(listener('syslog', 'Device logs (syslog)', choices.syslog, LISTEN.syslog, syslogIn, null));
  checks.push(listener('netflow', 'NetFlow and IPFIX', choices.netflow, LISTEN.netflow, netflowIn, flowSeries));
  checks.push(listener('sflow', 'sFlow', choices.sflow, LISTEN.sflow, sflowIn, flowSeries));
  return checks;
}

export async function queryFoundDevices(group: string): Promise<FoundDevice[]> {
  const rows = await promQuery(`discovery_snmp_device_info{group="${promLabel(group)}"}`);
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
