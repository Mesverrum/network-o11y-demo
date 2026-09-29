import React, { useCallback, useEffect, useState } from 'react';
import { Alert, ClipboardButton, Field, Input, Select } from '@grafana/ui';
import { useNavigate } from 'react-router-dom';
import { HelpButton, HubFrame } from '../components/HubFrame';
import { PLUGIN_BASE_URL } from '../constants';
import {
  Collector,
  INSTALL_ID,
  NETWORK_ALLOY_IMAGE,
  fleetCall,
  installCommand,
  readDraft,
  readStackId,
  validateCollectorName,
  writeDraft,
} from '../fleet';

function CollectorPage() {
  const navigate = useNavigate();
  const [collectors, setCollectors] = useState<Collector[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState(readDraft().collectorId);
  const [error, setError] = useState('');
  const [newName, setNewName] = useState('');
  const [stackId, setStackId] = useState('');
  const [knownAtLoad, setKnownAtLoad] = useState<string[]>([]);

  const loadCollectors = useCallback(async () => {
    const res = await fleetCall<{ collectors?: Collector[] }>('collector.v1.CollectorService/ListCollectors', {});
    return res.collectors || [];
  }, []);

  useEffect(() => {
    let cancel = false;
    loadCollectors()
      .then((list) => {
        if (cancel) {
          return;
        }
        setCollectors(list);
        setKnownAtLoad(list.map((c) => c.id));
        setLoaded(true);
        if (!list.some((c) => c.id === selected) && list.some((c) => c.id === 'hub-canary')) {
          setSelected('hub-canary');
        }
      })
      .catch((err: unknown) => {
        if (!cancel) {
          setLoaded(true);
          setError(err instanceof Error ? err.message : 'Fleet is not reachable from this Grafana.');
        }
      });
    readStackId()
      .then((id) => !cancel && setStackId(id))
      .catch(() => {});
    return () => {
      cancel = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadCollectors]);

  const installing = selected === INSTALL_ID;
  const nameError = !newName
    ? null
    : knownAtLoad.includes(newName)
      ? `${newName} is already in Fleet. Pick it from the list instead.`
      : validateCollectorName(newName);
  const checkedIn = installing && !!newName && !nameError && collectors.some((c) => c.id === newName);

  useEffect(() => {
    if (!installing || !newName || nameError || checkedIn) {
      return;
    }
    const timer = window.setInterval(() => {
      loadCollectors()
        .then(setCollectors)
        .catch(() => {});
    }, 10000);
    return () => window.clearInterval(timer);
  }, [installing, newName, nameError, checkedIn, loadCollectors]);

  const options = [
    ...collectors.map((c) => ({
      label: c.id,
      value: c.id,
      description: c.attributes?.role || 'Fleet collector',
    })),
    {
      label: 'Install a new collector',
      value: INSTALL_ID,
      description: 'For devices none of these collectors can reach',
    },
  ];

  const chosenId = installing ? newName : selected;

  return (
    <HubFrame
      stepId="collector"
      title="Collector"
      helpId="collector"
      intro="Pick the Network Alloy that can reach this segment. Choose it from the list, or install a new one if none of them can reach these devices."
      onContinue={() => {
        const draft = readDraft();
        draft.collectorId = chosenId;
        writeDraft(draft);
        navigate(`${PLUGIN_BASE_URL}/group`);
      }}
      continueDisabled={installing ? !checkedIn : !selected}
    >
      {error && <Alert title="Fleet">{error}</Alert>}
      <Select
        options={options}
        value={selected}
        onChange={(item) => setSelected(String(item.value ?? ''))}
        placeholder={loaded ? 'Choose a collector' : 'Loading collectors…'}
        width={50}
        isLoading={!loaded}
      />

      {!installing && selected && <p>Selected: {selected}. Groups you add go to this collector only.</p>}

      {installing && (
        <div>
          <h4>
            Install on a server that can reach those devices <HelpButton id="install" />
          </h4>
          <p>
            You run one command on that server. It starts the Network Alloy and connects it to Fleet. Groups you add
            after this go to that collector only. Your other collectors are not touched.
          </p>
          <Field
            label="Collector name"
            description="How it shows up in Fleet. Lowercase, e.g. branch3-collector."
            invalid={!!nameError}
            error={nameError}
          >
            <Input
              width={40}
              value={newName}
              placeholder="branch3-collector"
              onChange={(e) => setNewName(e.currentTarget.value.trim())}
            />
          </Field>

          {newName && !nameError && !checkedIn && (
            <>
              <p>
                Before you run it, put the credential file next to it as <code>snmp-auths.yml</code>
                <HelpButton id="credentials" />. Replace the three values in angle brackets with a Fleet token and your
                OpenTelemetry token. Those stay on the server.
              </p>
              <pre style={{ whiteSpace: 'pre-wrap' }}>{installCommand(newName, stackId)}</pre>
              <ClipboardButton icon="copy" variant="secondary" getText={() => installCommand(newName, stackId)}>
                Copy command
              </ClipboardButton>
              <Alert severity="info" title={`Waiting for ${newName} to check in`}>
                This page checks Fleet every 10 seconds. Continue turns on once {newName} shows up. In this lab, the
                image {NETWORK_ALLOY_IMAGE} only exists on the colocated AWS host.
              </Alert>
            </>
          )}

          {checkedIn && (
            <Alert severity="success" title={`${newName} checked in`}>
              Fleet can see it. Continue to give it its first group.
            </Alert>
          )}
        </div>
      )}
    </HubFrame>
  );
}

export default CollectorPage;
