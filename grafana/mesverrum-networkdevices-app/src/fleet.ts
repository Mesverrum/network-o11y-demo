import { getBackendSrv } from '@grafana/runtime';
import { lastValueFrom } from 'rxjs';
import { ProfileCatalog, bakedCatalog, profileLabel } from './profiles';
import {
  DeviceOverride,
  emptyOverride,
  groupOfAddress,
  isBlankOverride,
  parseOverrides,
  restampHubRevision,
  setDeviceOverride,
} from './river';

const HUB_PROXY = '/api/plugin-proxy/mesverrum-networkinstrumentationhub-app';

export type { DeviceOverride };
export { emptyOverride, isBlankOverride };

export type DeviceRow = {
  name: string;
  address: string;
  auth: string;
  sysObjectID: string;
  group: string;
  collector: string;
  pipelineName: string;
  forced: string;
  removed: boolean;
  libraryHash: string;
};

type PromSample = { metric?: Record<string, string>; value?: [number, string] };

type PromQuery = { data?: { result?: PromSample[] } };

export type FleetPipeline = {
  name?: string;
  contents?: string;
  matchers?: string[];
  enabled?: boolean;
};

type PipelineList = { pipelines?: FleetPipeline[]; items?: FleetPipeline[] };

async function fleetCall<T>(rpc: string, body: unknown): Promise<T> {
  const response = await lastValueFrom(
    getBackendSrv().fetch<T>({
      url: `${HUB_PROXY}/fleet/${rpc}`,
      method: 'POST',
      data: body,
      showErrorAlert: false,
    })
  );
  return response.data;
}

async function promQuery(expr: string): Promise<PromSample[]> {
  const response = await lastValueFrom(
    getBackendSrv().fetch<PromQuery>({
      url: `${HUB_PROXY}/stack/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query`,
      method: 'GET',
      params: { query: expr },
      showErrorAlert: false,
    })
  );
  return response.data?.data?.result || [];
}

export async function listPipelines(): Promise<FleetPipeline[]> {
  const data = await fleetCall<PipelineList>('pipeline.v1.PipelineService/ListPipelines', {});
  return data.pipelines || data.items || [];
}

function pipelineListHasGroup(contents: string, group: string): boolean {
  return new RegExp(`name\\s*=\\s*"${group.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}"`).test(contents);
}

/** The Fleet pipeline that already polls this collector and group. */
export function pipelineForDevice(
  device: { collector: string; group: string },
  pipelines: FleetPipeline[]
): FleetPipeline | null {
  const byId = pipelines.filter((pipeline) =>
    (pipeline.matchers || []).some((matcher) => matcher.includes(`collector.ID="${device.collector}"`))
  );
  const candidates = byId.length
    ? byId
    : pipelines.filter((pipeline) => (pipeline.contents || '').includes(`"${device.collector}"`));
  const grouped = candidates.filter((pipeline) => pipelineListHasGroup(pipeline.contents || '', device.group));
  const pool = grouped.length ? grouped : candidates;
  if (pool.length === 1) {
    return pool[0];
  }
  const hubName = `hub_${device.group.replace(/[^A-Za-z0-9_]/g, '_')}`;
  return pool.find((pipeline) => pipeline.name === hubName) || pool[0] || null;
}

function overrideFor(address: string, contents: string): DeviceOverride {
  return parseOverrides(contents).find((ov) => ov.address === address) || emptyOverride(address);
}

async function libraryHashes(): Promise<Map<string, string>> {
  const rows = await promQuery('max by (collector, library_hash) (discovery_snmp_library_info)');
  const out = new Map<string, string>();
  for (const row of rows) {
    const collector = row.metric?.collector || '';
    const hash = row.metric?.library_hash || '';
    if (collector && hash) {
      out.set(collector, hash);
    }
  }
  return out;
}

/**
 * Prefer the collector HTTP catalog (one series in Mimir for the hash only).
 * Fall back to the plugin-baked JSON when the collector is unreachable.
 */
export async function loadCatalog(pipelineName: string, collector: string): Promise<ProfileCatalog> {
  const baked = bakedCatalog();
  if (!pipelineName) {
    return baked;
  }
  const paths = [
    `${HUB_PROXY}/canary-http/api/v0/component/remotecfg/${pipelineName}.default/discovery.snmp.hub/fingerprints`,
    `${HUB_PROXY}/canary-http/api/v0/component/remotecfg/${pipelineName}.default/discovery.snmp.hub/`,
  ];
  for (const url of paths) {
    try {
      const response = await lastValueFrom(
        getBackendSrv().fetch<Omit<ProfileCatalog, 'origin'>>({
          url,
          method: 'GET',
          showErrorAlert: false,
        })
      );
      const data = response.data;
      if (data?.profiles?.length && data.library_hash) {
        return { ...data, origin: 'collector' };
      }
    } catch {
      // try the next path
    }
  }
  if (collector) {
    try {
      const hashes = await libraryHashes();
      const live = hashes.get(collector);
      if (live && live !== baked.library_hash) {
        return {
          ...baked,
          library_hash: `${baked.library_hash} (collector reports ${live})`,
          origin: 'plugin',
        };
      }
    } catch {
      // keep baked
    }
  }
  return baked;
}

export async function loadDevices(): Promise<DeviceRow[]> {
  const [samples, pipelines, hashes] = await Promise.all([
    promQuery('max by (device_name, address, auth, sysObjectID, group, collector) (discovery_snmp_device_info)'),
    listPipelines(),
    libraryHashes().catch(() => new Map<string, string>()),
  ]);
  const catalog = bakedCatalog();
  const rows = new Map<string, DeviceRow>();
  for (const sample of samples) {
    const metric = sample.metric || {};
    const address = metric.address || '';
    const collector = metric.collector || '';
    const group = metric.group || '';
    if (!address || !collector) {
      continue;
    }
    const pipeline = pipelineForDevice({ collector, group }, pipelines);
    const ov = pipeline?.contents ? overrideFor(address, pipeline.contents) : emptyOverride(address);
    const key = `${collector}|${address}`;
    rows.set(key, {
      name: metric.device_name || address,
      address,
      auth: metric.auth || '',
      sysObjectID: metric.sysObjectID || '',
      group,
      collector,
      pipelineName: pipeline?.name || '',
      forced: profileLabel(catalog, ov.moduleHot, ov.moduleCold, ov.moduleTopology),
      removed: ov.ignore,
      libraryHash: hashes.get(collector) || '',
    });
  }
  for (const pipeline of pipelines) {
    const contents = pipeline.contents || '';
    for (const ov of parseOverrides(contents)) {
      const already = [...rows.values()].some((row) => row.address === ov.address && row.pipelineName === (pipeline.name || ''));
      if (already || isBlankOverride(ov)) {
        continue;
      }
      const group = groupOfAddress(contents, ov.address);
      rows.set(`override|${pipeline.name}|${ov.address}`, {
        name: ov.name || ov.address,
        address: ov.address,
        auth: ov.auth,
        sysObjectID: '',
        group,
        collector: '',
        pipelineName: pipeline.name || '',
        forced: ov.ignore ? 'removed' : profileLabel(catalog, ov.moduleHot, ov.moduleCold, ov.moduleTopology),
        removed: ov.ignore,
        libraryHash: '',
      });
    }
  }
  return [...rows.values()].sort((a, b) =>
    `${a.collector}|${a.group}|${a.name}`.localeCompare(`${b.collector}|${b.group}|${b.name}`)
  );
}

export async function readOverride(pipelineName: string, address: string): Promise<DeviceOverride> {
  const pipeline = (await listPipelines()).find((item) => item.name === pipelineName);
  if (!pipeline?.contents) {
    return emptyOverride(address);
  }
  return overrideFor(address, pipeline.contents);
}

export async function saveOverride(pipelineName: string, group: string, ov: DeviceOverride): Promise<void> {
  const pipeline = (await listPipelines()).find((item) => item.name === pipelineName);
  if (!pipeline?.contents) {
    throw new Error(`Fleet pipeline ${pipelineName} has no config to edit.`);
  }
  if (!pipeline.matchers?.length) {
    throw new Error(`Fleet pipeline ${pipelineName} has no matchers.`);
  }
  const edited = restampHubRevision(setDeviceOverride(pipeline.contents, group, ov));
  await fleetCall('pipeline.v1.PipelineService/UpsertPipeline', {
    pipeline: {
      name: pipeline.name,
      contents: edited,
      matchers: pipeline.matchers,
      enabled: pipeline.enabled !== false,
    },
  });
  syncHubIgnore(group, ov);
}

function syncHubIgnore(group: string, ov: DeviceOverride) {
  const hubGroup = sessionStorage.getItem('hub.name') || 'hub-demo';
  const hubCollector = sessionStorage.getItem('hub.collectorId') || 'hub-canary';
  if (group !== hubGroup) {
    return;
  }
  if (sessionStorage.getItem('hub.collectorId') && sessionStorage.getItem('hub.collectorId') !== hubCollector) {
    return;
  }
  const current = (sessionStorage.getItem('hub.ignores') || '')
    .split(/[\s,]+/)
    .map((ip) => ip.trim())
    .filter(Boolean);
  const next = ov.ignore
    ? [...new Set([...current, ov.address])].sort()
    : current.filter((ip) => ip !== ov.address);
  sessionStorage.setItem('hub.ignores', next.join('\n'));
}
