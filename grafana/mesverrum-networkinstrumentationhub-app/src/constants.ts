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
    body: 'Name, note, ranges, and login nicknames. Start discovery writes the scan to the collector.',
  },
  {
    id: 'found',
    title: 'What we found',
    body: 'Devices that answered, from discovery_snmp_device_info.',
  },
  {
    id: 'collect',
    title: 'What to collect',
    body: 'Health and port names are always on. Pick neighbor topology, alarms, logs, and flow.',
  },
  {
    id: 'apply',
    title: 'Apply',
    body: 'Dry run. Shows the settings that would go to that one collector. Nothing is written yet.',
  },
  {
    id: 'receiving',
    title: 'Receiving',
    body: 'Polling goes ready after Apply. Alarms, logs, and traffic stay listening until the device sends them. Devices are a separate app.',
  },
] as const;
