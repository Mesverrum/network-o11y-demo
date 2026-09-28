import pluginJson from './plugin.json';

export const PLUGIN_BASE_URL = `/a/${pluginJson.id}`;

export const STEPS = [
  {
    id: 'collector',
    title: 'Collector',
    body: 'Pick the Network Alloy that can reach this segment. An application Alloy is listed and cannot be selected.',
  },
  {
    id: 'group',
    title: 'Add a group',
    body: 'Name, note, address ranges, and a login nickname the collector reported from its credential file.',
  },
  {
    id: 'found',
    title: 'What we found',
    body: 'Devices that answered. Tick the ones to watch.',
  },
  {
    id: 'collect',
    title: 'What to collect',
    body: 'Health and names stay on. Neighbors, alarms, device logs, and traffic details are choices.',
  },
  {
    id: 'apply',
    title: 'Apply',
    body: 'Dry run. Shows the settings that would go to that one collector. Nothing is written yet.',
  },
  {
    id: 'receiving',
    title: 'Receiving',
    body: 'Polling goes ready after Apply. Alarms, logs, and traffic stay listening until the device sends them.',
  },
  {
    id: 'devices',
    title: 'Devices',
    body: 'The device list: open one device, or change several together.',
  },
] as const;
