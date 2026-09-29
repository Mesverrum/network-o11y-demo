/** Device override editing for discovery.snmp. The hub copy is src/deviceOverrides.ts. */

export type DeviceOverride = {
  address: string;
  ignore: boolean;
  name: string;
  auth: string;
  moduleHot: string;
  moduleCold: string;
  moduleTopology: string;
};

const SLOT = '__HUB_REVISION__';

export function emptyOverride(address: string): DeviceOverride {
  return {
    address,
    ignore: false,
    name: '',
    auth: '',
    moduleHot: '',
    moduleCold: '',
    moduleTopology: '',
  };
}

export function isBlankOverride(ov: DeviceOverride): boolean {
  return !ov.ignore && !ov.name && !ov.auth && !ov.moduleHot && !ov.moduleCold && !ov.moduleTopology;
}

export function revisionOf(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, '0');
}

/** Put the hub_revision hash back after an edit. Pipelines without that label are unchanged. */
export function restampHubRevision(river: string): string {
  if (!river.includes('target_label = "hub_revision"')) {
    return river;
  }
  const withSlot = river.replace(
    /(target_label = "hub_revision"\s+replacement\s+= ")(?:[0-9a-f]{8}|__HUB_REVISION__)(")/,
    '$1' + SLOT + '$2'
  );
  return withSlot.split(SLOT).join(revisionOf(withSlot));
}

type Span = { start: number; end: number; body: string };

function discoverySpans(river: string): Span[] {
  const spans: Span[] = [];
  const re = /discovery\.snmp\s+"[^"]*"\s*\{/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(river))) {
    const open = match.index + match[0].length - 1;
    const close = matchBrace(river, open);
    if (close < 0) {
      continue;
    }
    spans.push({ start: open + 1, end: close, body: river.slice(open + 1, close) });
    re.lastIndex = close + 1;
  }
  return spans;
}

function matchBrace(text: string, open: number): number {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
      i++;
      while (i < text.length && text[i] !== '"') {
        if (text[i] === '\\') {
          i++;
        }
        i++;
      }
    } else if (c === '`') {
      i++;
      while (i < text.length && text[i] !== '`') {
        i++;
      }
    } else if (c === '/' && text[i + 1] === '/') {
      while (i < text.length && text[i] !== '\n') {
        i++;
      }
    } else if (c === '{') {
      depth++;
    } else if (c === '}') {
      depth--;
      if (depth === 0) {
        return i;
      }
    }
  }
  return -1;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function blockHasGroup(body: string, group: string): boolean {
  return new RegExp(`name\\s*=\\s*"${escapeRegExp(group)}"`).test(body);
}

function quote(value: string): string {
  return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

function unquote(value: string): string {
  return value.replace(/\\"/g, '"').replace(/\\\\/g, '\\');
}

function field(block: string, name: string): string {
  const match = new RegExp(`(?:^|\\n)\\s*${name}\\s*=\\s*"((?:\\\\.|[^"\\\\])*)"`).exec(block);
  return match ? unquote(match[1]) : '';
}

function overridePattern(): RegExp {
  return /[ \t]*override\s*\{[^}]*\}[ \t]*(?:\r?\n)?/g;
}

export function parseOverrides(river: string): DeviceOverride[] {
  const found: DeviceOverride[] = [];
  for (const match of river.matchAll(overridePattern())) {
    const block = match[0];
    const address = field(block, 'address');
    if (!address) {
      continue;
    }
    found.push({
      address,
      ignore: /ignore\s*=\s*true/.test(block),
      name: field(block, 'name'),
      auth: field(block, 'auth'),
      moduleHot: field(block, 'module_hot'),
      moduleCold: field(block, 'module_cold'),
      moduleTopology: field(block, 'module_topology'),
    });
  }
  return found;
}

export function renderOverride(ov: DeviceOverride): string {
  const lines = [`    address = ${quote(ov.address)}`];
  if (ov.ignore) {
    lines.push('    ignore  = true');
  }
  if (ov.name) {
    lines.push(`    name    = ${quote(ov.name)}`);
  }
  if (ov.auth) {
    lines.push(`    auth    = ${quote(ov.auth)}`);
  }
  if (ov.moduleHot) {
    lines.push(`    module_hot = ${quote(ov.moduleHot)}`);
  }
  if (ov.moduleCold) {
    lines.push(`    module_cold = ${quote(ov.moduleCold)}`);
  }
  if (ov.moduleTopology) {
    lines.push(`    module_topology = ${quote(ov.moduleTopology)}`);
  }
  return `  override {\n${lines.join('\n')}\n  }\n`;
}

function stripAddress(body: string, address: string): string {
  return body.replace(overridePattern(), (block) => (field(block, 'address') === address ? '' : block));
}

/** Insert or remove one address's override inside the discovery.snmp block that owns the group. */
export function setDeviceOverride(river: string, group: string, ov: DeviceOverride): string {
  const span = discoverySpans(river).find((item) => blockHasGroup(item.body, group));
  if (!span) {
    throw new Error(`No discovery.snmp block contains group ${group}.`);
  }
  let body = stripAddress(span.body, ov.address);
  if (!isBlankOverride(ov)) {
    body = body.replace(/\s*$/, '\n') + renderOverride(ov);
  }
  return river.slice(0, span.start) + body + river.slice(span.end);
}

export function groupOfAddress(river: string, address: string): string {
  for (const span of discoverySpans(river)) {
    if (!parseOverrides(span.body).some((ov) => ov.address === address)) {
      continue;
    }
    const names = [...span.body.matchAll(/name\s*=\s*"([^"]+)"/g)].map((match) => match[1]);
    return names[0] || '';
  }
  return '';
}

/**
 * Keep name, login, and module forces when the hub rebuilds a pipeline.
 * Ignore stays owned by the hub draft: an address in `ignores` is not copied back.
 */
export function preserveProfileOverrides(river: string, existing: string, ignores: string[]): string {
  const ignored = new Set(ignores);
  let next = river;
  for (const ov of parseOverrides(existing)) {
    if (ignored.has(ov.address)) {
      continue;
    }
    if (!ov.name && !ov.auth && !ov.moduleHot && !ov.moduleCold && !ov.moduleTopology) {
      continue;
    }
    if (parseOverrides(next).some((item) => item.address === ov.address)) {
      continue;
    }
    const group = groupOfAddress(existing, ov.address);
    if (!group) {
      continue;
    }
    try {
      next = setDeviceOverride(next, group, { ...ov, ignore: false });
    } catch {
      continue;
    }
  }
  return restampHubRevision(next);
}
