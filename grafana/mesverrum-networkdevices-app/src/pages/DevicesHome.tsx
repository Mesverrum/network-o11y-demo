import React, { useEffect, useMemo, useState } from 'react';
import { PluginPage } from '@grafana/runtime';
import { Alert, Button, Field, Input, RadioButtonGroup, Select } from '@grafana/ui';
import {
  DeviceOverride,
  DeviceRow,
  emptyOverride,
  isBlankOverride,
  loadCatalog,
  loadDevices,
  readOverride,
  saveOverride,
} from '../fleet';
import { ProfileCatalog, bakedCatalog, matchingProfile, profileByName } from '../profiles';

const WIZARD = '/a/mesverrum-networkinstrumentationhub-app/collector';

function DevicesHome() {
  const [selected, setSelected] = useState<DeviceRow | null>(null);
  if (selected) {
    return <DevicePage device={selected} onBack={() => setSelected(null)} />;
  }
  return <DeviceList onEdit={setSelected} />;
}

function DeviceList({ onEdit }: { onEdit: (device: DeviceRow) => void }) {
  const [devices, setDevices] = useState<DeviceRow[]>([]);
  const [filter, setFilter] = useState('');
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancel = false;
    const load = () => {
      loadDevices()
        .then((rows) => {
          if (cancel) {
            return;
          }
          setDevices(rows);
          setError('');
          setLoaded(true);
        })
        .catch((err: unknown) => {
          if (!cancel) {
            setLoaded(true);
            setError(err instanceof Error ? err.message : 'Could not read devices.');
          }
        });
    };
    load();
    const timer = window.setInterval(load, 15000);
    return () => {
      cancel = true;
      window.clearInterval(timer);
    };
  }, []);

  const needle = filter.trim().toLowerCase();
  const visible = devices.filter((device) => {
    if (!needle) {
      return true;
    }
    return `${device.name} ${device.address} ${device.group} ${device.collector} ${device.forced}`
      .toLowerCase()
      .includes(needle);
  });

  return (
    <PluginPage>
      <h2>Network devices</h2>
      <p>
        Devices the collectors are already polling. Open one to remove it or force a profile. Discovery, listeners, and
        scrape intervals stay in the Instrumentation Hub.
      </p>
      {error && (
        <Alert title="Could not load devices" severity="error">
          {error}
        </Alert>
      )}
      <Field label="Filter">
        <Input value={filter} onChange={(event) => setFilter(event.currentTarget.value)} placeholder="name, address, group" width={40} />
      </Field>
      {!error && visible.length === 0 && <p>{loaded ? 'No devices reported yet.' : 'Checking the last scan…'}</p>}
      {visible.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Device</th>
              <th>Address</th>
              <th>Group</th>
              <th>Collector</th>
              <th>Profile</th>
              <th>Library</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {visible.map((device) => (
              <tr key={`${device.pipelineName}|${device.collector}|${device.address}`}>
                <td>{device.name}</td>
                <td>{device.address}</td>
                <td>{device.group}</td>
                <td>{device.collector || device.pipelineName}</td>
                <td>{device.removed ? 'removed' : device.forced || 'fingerprint'}</td>
                <td>{device.libraryHash || '—'}</td>
                <td>
                  <Button size="sm" onClick={() => onEdit(device)} disabled={!device.pipelineName || !device.group}>
                    Edit
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p>
        <Button variant="secondary" onClick={() => window.location.assign(WIZARD)}>
          Open the discovery wizard
        </Button>
      </p>
    </PluginPage>
  );
}

function DevicePage({ device, onBack }: { device: DeviceRow; onBack: () => void }) {
  const [catalog, setCatalog] = useState<ProfileCatalog>(bakedCatalog());
  const [ignore, setIgnore] = useState(false);
  const [name, setName] = useState('');
  const [auth, setAuth] = useState('');
  const [profile, setProfile] = useState('');
  const [hot, setHot] = useState('');
  const [cold, setCold] = useState('');
  const [topology, setTopology] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancel = false;
    Promise.all([readOverride(device.pipelineName, device.address), loadCatalog(device.pipelineName, device.collector)])
      .then(([ov, nextCatalog]) => {
        if (cancel) {
          return;
        }
        setCatalog(nextCatalog);
        applyOverride(ov, nextCatalog);
        setReady(true);
      })
      .catch((err: unknown) => {
        if (!cancel) {
          setReady(true);
          setError(err instanceof Error ? err.message : 'Could not read the pipeline.');
        }
      });
    return () => {
      cancel = true;
    };
  }, [device.address, device.pipelineName, device.collector]);

  const options = useMemo(() => catalog.profiles.map((item) => ({ label: item.name, value: item.name })), [catalog]);
  const selected = options.find((item) => item.value === profile) || null;

  const applyOverride = (ov: DeviceOverride, cat: ProfileCatalog) => {
    setIgnore(ov.ignore);
    setName(ov.name);
    setAuth(ov.auth);
    setHot(ov.moduleHot);
    setCold(ov.moduleCold);
    setTopology(ov.moduleTopology);
    setProfile(matchingProfile(cat, ov.moduleHot, ov.moduleCold, ov.moduleTopology));
  };

  const onHot = (value: string) => {
    setHot(value);
    setProfile(matchingProfile(catalog, value, cold, topology));
  };
  const onCold = (value: string) => {
    setCold(value);
    setProfile(matchingProfile(catalog, hot, value, topology));
  };
  const onTopology = (value: string) => {
    setTopology(value);
    setProfile(matchingProfile(catalog, hot, cold, value));
  };

  const chooseProfile = (value: string) => {
    if (!value) {
      setProfile(matchingProfile(catalog, hot, cold, topology));
      return;
    }
    const picked = profileByName(catalog, value);
    setProfile(value);
    if (!picked) {
      return;
    }
    setHot(picked.hot.join(', '));
    setCold(picked.cold.join(', '));
    setTopology(picked.topology.join(', '));
  };

  const useFingerprint = () => {
    setHot('');
    setCold('');
    setTopology('');
    setProfile('');
  };

  const persist = (ov: DeviceOverride, success: string) => {
    setBusy(true);
    setError('');
    setNotice('');
    saveOverride(device.pipelineName, device.group, ov)
      .then(() => {
        applyOverride(ov, catalog);
        setNotice(success);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Fleet rejected the change.');
      })
      .finally(() => setBusy(false));
  };

  const save = () => {
    const ov: DeviceOverride = ignore
      ? { ...emptyOverride(device.address), ignore: true }
      : {
          address: device.address,
          ignore: false,
          name: name.trim(),
          auth: auth.trim(),
          moduleHot: hot.trim(),
          moduleCold: cold.trim(),
          moduleTopology: topology.trim(),
        };
    const success = ov.ignore
      ? `Fleet has the ignore for ${device.address}. The collector drops it as soon as it loads this config.`
      : isBlankOverride(ov)
        ? `${device.address} is using the fingerprint again.`
        : `Fleet has the override for ${device.address}. The collector rescans as soon as it loads this config.`;
    persist(ov, success);
  };

  const clearOverride = () => {
    persist(emptyOverride(device.address), `${device.address} is using the fingerprint again.`);
  };

  const catalogNote =
    catalog.origin === 'collector'
      ? `Profile list from this collector · library_hash ${catalog.library_hash} · ${catalog.profiles.length} profiles`
      : `Profile list from the plugin (collector catalog unreachable) · library_hash ${catalog.library_hash} · ${catalog.profiles.length} profiles`;

  return (
    <PluginPage>
      <h2>Device</h2>
      <p>
        <Button variant="secondary" size="sm" onClick={onBack}>
          Back
        </Button>
      </p>
      <p>
        {device.name} · {device.address}
        <br />
        Group {device.group || 'unknown'} · collector {device.collector || 'unknown'} · pipeline {device.pipelineName}
        <br />
        Answered as {device.auth || 'an unknown login'}
        {device.sysObjectID ? ` · sysObjectID ${device.sysObjectID}` : ''}
      </p>
      <Alert title="Fingerprint library" severity={catalog.origin === 'collector' ? 'info' : 'warning'}>
        {catalogNote}
      </Alert>
      <p>
        sysObjectID picks the modules. Choose a profile to force different lists on this address only. Blank tier stays
        on the fingerprint. An empty list does not turn a tier off. Custom profiles in the collector image show up here
        when the catalog comes from the collector.
      </p>
      {error && (
        <Alert title="Fleet" severity="error">
          {error}
        </Alert>
      )}
      {notice && (
        <Alert title="Override" severity="success">
          {notice}
        </Alert>
      )}
      {!ready && <p>Reading the pipeline…</p>}
      {ready && (
        <>
          <Field label="Polling">
            <RadioButtonGroup
              options={[
                { label: 'Keep', value: 'keep' },
                { label: 'Remove', value: 'remove' },
              ]}
              value={ignore ? 'remove' : 'keep'}
              onChange={(value) => setIgnore(value === 'remove')}
            />
          </Field>
          {!ignore && (
            <>
              <Field label="Name" description="Optional. Blank keeps the name from the scan.">
                <Input id="device-name" value={name} onChange={(event) => setName(event.currentTarget.value)} width={40} />
              </Field>
              <Field label="Login" description="A name from the collector's SNMP_AUTHS file. This page never stores a community string.">
                <Input id="device-auth" value={auth} onChange={(event) => setAuth(event.currentTarget.value)} width={40} placeholder="public_v2" />
              </Field>
              <Field label="Profile" description="Profiles from this collector's image when available.">
                <Select
                  inputId="device-profile"
                  options={options}
                  value={selected}
                  onChange={(item) => chooseProfile(item?.value == null ? '' : String(item.value))}
                  isClearable
                  placeholder="Fingerprint"
                  width={60}
                />
              </Field>
              <Field label="Hot modules" description="Comma-separated. Blank leaves this tier on the fingerprint.">
                <Input id="module-hot" value={hot} onChange={(event) => onHot(event.currentTarget.value)} width={60} />
              </Field>
              <Field label="Cold modules" description="Comma-separated. Blank leaves this tier on the fingerprint.">
                <Input id="module-cold" value={cold} onChange={(event) => onCold(event.currentTarget.value)} width={60} />
              </Field>
              <Field label="Topology modules" description="Comma-separated. Blank leaves this tier on the fingerprint.">
                <Input id="module-topology" value={topology} onChange={(event) => onTopology(event.currentTarget.value)} width={60} />
              </Field>
              <p>
                <Button variant="secondary" onClick={useFingerprint} disabled={busy}>
                  Use the fingerprint
                </Button>
              </p>
            </>
          )}
          <p>
            <Button onClick={save} disabled={busy}>
              Save
            </Button>{' '}
            <Button variant="secondary" onClick={clearOverride} disabled={busy}>
              Clear override
            </Button>
          </p>
        </>
      )}
    </PluginPage>
  );
}

export default DevicesHome;
