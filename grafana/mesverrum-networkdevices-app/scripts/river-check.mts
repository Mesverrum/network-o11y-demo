import {
  emptyOverride,
  isBlankOverride,
  parseOverrides,
  preserveProfileOverrides,
  renderOverride,
  restampHubRevision,
  revisionOf,
  setDeviceOverride,
} from '../src/river.ts';

function assert(cond: boolean, message: string) {
  if (!cond) {
    throw new Error(message);
  }
}

const SLOT = '__HUB_REVISION__';

function stamp(river: string): string {
  return river.split(SLOT).join(revisionOf(river));
}

const BASE = `discovery.snmp "hub" {
  group {
    name = "hub-demo"
  }
}
prometheus.relabel "hub_self" {
  rule {
    target_label = "hub_revision"
    replacement  = "${SLOT}"
  }
}
`;

const stamped = stamp(BASE);
assert(restampHubRevision(stamped) === stamped, 'restamp is stable when nothing changed');
assert(restampHubRevision(restampHubRevision(stamped)) === restampHubRevision(stamped), 'restamp is idempotent');

const forced = setDeviceOverride(stamped, 'hub-demo', {
  address: '172.20.20.9',
  ignore: false,
  name: 'edge',
  auth: 'public_v2',
  moduleHot: 'if_mib',
  moduleCold: 'if_mib_meta, ip_addr, ucd_mib, barracuda_email_gateway',
  moduleTopology: '',
});
assert(!forced.includes('module_topology'), 'an empty topology list is omitted');
assert(forced.includes('module_hot = "if_mib"'), 'hot modules are written');
assert(forced.includes('barracuda_email_gateway'), 'cold modules are written');
const parsed = parseOverrides(forced);
assert(parsed.length === 1, 'one override');
assert(parsed[0].moduleCold.includes('barracuda_email_gateway'), 'cold modules parse back');
assert(parsed[0].moduleTopology === '', 'omitted topology parses as empty');
assert(parsed[0].name === 'edge', 'name parses back');

const removed = setDeviceOverride(forced, 'hub-demo', emptyOverride('172.20.20.9'));
assert(parseOverrides(removed).length === 0, 'a blank override removes the block');
assert(isBlankOverride(emptyOverride('172.20.20.9')), 'blank helper');

const ignoreOnly = setDeviceOverride(stamped, 'hub-demo', { ...emptyOverride('172.20.20.4'), ignore: true });
assert(renderOverride(parseOverrides(ignoreOnly)[0]).includes('ignore  = true'), 'ignore round-trips');

const rebuilt = stamp(BASE);
const kept = preserveProfileOverrides(rebuilt, forced, []);
assert(parseOverrides(kept).some((ov) => ov.address === '172.20.20.9' && ov.moduleHot === 'if_mib'), 'rebuild keeps a profile force');
assert(kept.includes('target_label = "hub_revision"'), 'revision label survives');
assert(!kept.includes(SLOT), 'revision slot is replaced');

const dropped = preserveProfileOverrides(rebuilt, forced, ['172.20.20.9']);
assert(!parseOverrides(dropped).some((ov) => ov.address === '172.20.20.9'), 'an ignored address is not copied back');

const ignoreDropped = preserveProfileOverrides(rebuilt, ignoreOnly, []);
assert(parseOverrides(ignoreDropped).length === 0, 'ignore-only blocks are not profile forces');

let threw = false;
try {
  setDeviceOverride(stamped, 'missing-group', emptyOverride('1.2.3.4'));
} catch {
  threw = true;
}
assert(threw, 'unknown group throws');

const fabric = `discovery.snmp "fabric" {
  group { name = "hq" }
  group { name = "branch1" }
}
`;
const fabricEdited = setDeviceOverride(fabric, 'branch1', {
  ...emptyOverride('10.0.0.8'),
  moduleHot: 'if_mib',
});
assert(parseOverrides(fabricEdited).length === 1, 'override lands in the block that owns the group');

console.log('river-check ok');
