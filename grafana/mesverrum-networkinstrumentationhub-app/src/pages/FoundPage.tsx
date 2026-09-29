import React, { useEffect, useState } from 'react';
import { Alert } from '@grafana/ui';
import { HelpButton, HubFrame } from '../components/HubFrame';
import { FoundDevice, discoveryName, queryFoundDevices, readDraft } from '../fleet';

function FoundPage() {
  const draft = readDraft();
  const started = discoveryName();
  const [devices, setDevices] = useState<FoundDevice[]>([]);
  const [error, setError] = useState('');
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (!started || !draft.name) {
      return;
    }
    let cancel = false;
    const load = () => {
      queryFoundDevices(draft.name)
        .then((rows) => {
          if (cancel) {
            return;
          }
          setDevices(rows);
          setError('');
          setChecked(true);
        })
        .catch((err: unknown) => {
          if (!cancel) {
            setChecked(true);
            setError(err instanceof Error ? err.message : 'Could not read discovery_snmp_device_info.');
          }
        });
    };
    load();
    const timer = window.setInterval(load, 15000);
    return () => {
      cancel = true;
      window.clearInterval(timer);
    };
  }, [draft.name, started]);

  return (
    <HubFrame
      stepId="found"
      title="What we found"
      helpId="importDevice"
      intro="These rows are devices that answered the scan. The page reads discovery_snmp_device_info. A known device is not written to the collector log."
    >
      <p>
        Group {draft.name || 'this group'}. <HelpButton id="importDevice" />
      </p>
      {!started && (
        <Alert title="Discovery has not been started" severity="warning">
          Go back to Add a group and choose Start discovery. Nothing is scanning until that config is on the collector.
        </Alert>
      )}
      {error && (
        <Alert title="Could not read the scan" severity="error">
          {error}
        </Alert>
      )}
      {started && !error && devices.length === 0 && (
        <p>
          {checked
            ? `Nothing has answered for ${draft.name} yet. This page checks again every 15 seconds. A /24 takes about a minute, then another half minute before the metric shows up.`
            : 'Checking the last scan…'}
        </p>
      )}
      {devices.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Device</th>
              <th>Address</th>
              <th>Login that answered</th>
            </tr>
          </thead>
          <tbody>
            {devices.map((device) => (
              <tr key={`${device.name}-${device.address}`}>
                <td>{device.name}</td>
                <td>{device.address}</td>
                <td>{device.auth}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </HubFrame>
  );
}

export default FoundPage;
