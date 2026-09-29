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
    body: 'Devices that answered. Ignore drops an address from the catalog.',
  },
  {
    id: 'collect',
    title: 'What to collect',
    body: 'Health and port names are always on. Pick neighbor topology, alarms, logs, and flow.',
  },
  {
    id: 'apply',
    title: 'Apply',
    body: 'Writes the long-term pipeline, including any listeners you turned on, to that one collector.',
  },
  {
    id: 'receiving',
    title: 'Receiving',
    body: 'Confirms polled metrics and, for each listener, whether records are arriving. Devices are a separate app.',
  },
] as const;
