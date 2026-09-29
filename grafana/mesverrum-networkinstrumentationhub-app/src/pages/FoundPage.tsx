import React, { useEffect, useState } from 'react';
import { Alert, Button } from '@grafana/ui';
import { HelpButton, HubFrame } from '../components/HubFrame';
import {
  FoundDevice,
  discoveryName,
  pushDraft,
  queryFoundDevices,
  readChoices,
  readDraft,
  writeDraft,
} from '../fleet';

function FoundPage() {
  const started = discoveryName();
  const [draft, setDraft] = useState(readDraft());
  const [devices, setDevices] = useState<FoundDevice[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState('');

  useEffect(() => {
    if (!draft.name) {
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
  }, [draft.name]);

  const ignored = new Set(draft.ignores);
  const visible = devices.filter((device) => device.address && !ignored.has(device.address));
  const stillListed = draft.ignores.filter((ip) => devices.some((device) => device.address === ip));

  const push = (nextIgnores: string[], address: string, verb: string) => {
    const next = { ...readDraft(), ignores: nextIgnores };
    writeDraft(next);
    setDraft(next);
    setBusy(address);
    setError('');
    pushDraft(next, readChoices())
      .then(() => {
        setNotice(
          verb === 'ignore'
            ? `Fleet has the ignore for ${address}. The collector drops it as soon as it loads this config. Grafana keeps the last sample for a few minutes.`
            : `${address} is back in the scan. The next pass can find it again.`
        );
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Fleet rejected the change.');
      })
      .finally(() => setBusy(''));
  };

  return (
    <HubFrame
      stepId="found"
      title="What we found"
      helpId="importDevice"
      intro="These rows are devices that answered the scan. Ignore drops an address from the catalog and from polling. The collector rescans as soon as Fleet delivers the change."
    >
      <p>
        Group {draft.name || 'this group'}. <HelpButton id="importDevice" />
      </p>
      {!started && visible.length === 0 && draft.ignores.length === 0 && (
        <Alert title="Discovery has not been started in this browser" severity="info">
          The list below still reads whatever this group has already reported. Start discovery writes a new scan.
        </Alert>
      )}
      {error && (
        <Alert title="Fleet" severity="error">
          {error}
        </Alert>
      )}
      {notice && (
        <Alert title="Catalog" severity="success">
          {notice}
        </Alert>
      )}
      {!error && visible.length === 0 && draft.ignores.length === 0 && (
        <p>
          {checked
            ? `Nothing has answered for ${draft.name} yet. This page checks again every 15 seconds. A /24 takes about a minute, then another half minute before the metric shows up.`
            : 'Checking the last scan…'}
        </p>
      )}
      {visible.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Device</th>
              <th>Address</th>
              <th>Login that answered</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {visible.map((device) => (
              <tr key={`${device.name}-${device.address}`}>
                <td>{device.name}</td>
                <td>{device.address}</td>
                <td>{device.auth}</td>
                <td>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy !== ''}
                    onClick={() => push([...draft.ignores, device.address].sort(), device.address, 'ignore')}
                  >
                    {busy === device.address ? 'Saving…' : 'Ignore'}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {draft.ignores.length > 0 && (
        <>
          <h4>Ignored</h4>
          <p>These addresses are left out of the catalog. Restore puts one back on the next scan.</p>
          {stillListed.length > 0 && <p>Still in the last sample, dropping: {stillListed.join(', ')}.</p>}
          <table>
            <thead>
              <tr>
                <th>Address</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {draft.ignores.map((address) => (
                <tr key={address}>
                  <td>{address}</td>
                  <td>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busy !== ''}
                      onClick={() => push(draft.ignores.filter((ip) => ip !== address), address, 'restore')}
                    >
                      {busy === address ? 'Saving…' : 'Restore'}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </HubFrame>
  );
}

export default FoundPage;
