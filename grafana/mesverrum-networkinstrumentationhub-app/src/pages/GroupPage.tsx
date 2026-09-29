import React, { useState } from 'react';
import { Alert, Field, Input, MultiSelect, RadioButtonGroup, TextArea } from '@grafana/ui';
import { useNavigate } from 'react-router-dom';
import { HelpButton, HubFrame } from '../components/HubFrame';
import { PLUGIN_BASE_URL } from '../constants';
import {
  discoveryRiver,
  markDiscovery,
  parseRanges,
  readChoices,
  readDraft,
  upsertPipeline,
  validateAuths,
  validateGroupName,
  validateNote,
  validateRanges,
  writeChoices,
  writeDraft,
} from '../fleet';

function shown(value: string, check: (value: string) => string | null): string | undefined {
  return value.trim() ? check(value.trim()) || undefined : undefined;
}

function GroupPage() {
  const navigate = useNavigate();
  const initial = readDraft();
  const [name, setName] = useState(initial.name);
  const [description, setDescription] = useState(initial.description);
  const [ranges, setRanges] = useState(initial.cidrs.join('\n'));
  const [auths, setAuths] = useState(initial.auths);
  const [rescan, setRescan] = useState(readChoices().rescan);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const cidrs = parseRanges(ranges);
  const nameError = shown(name, validateGroupName);
  const noteError = validateNote(description.trim()) || undefined;
  const rangeError = ranges.trim() ? validateRanges(cidrs) || undefined : undefined;
  const authError = validateAuths(auths) || undefined;
  const ready = !validateGroupName(name.trim()) && !noteError && !validateRanges(cidrs) && !authError;

  return (
    <HubFrame
      stepId="group"
      title="Add a group"
      helpId="group"
      intro="Name the scan and leave a note for the next person. Logins here are nicknames from the credential file. Do not paste a password or community string. Start discovery writes that scan to the collector and runs it."
      continueLabel={busy ? 'Starting discovery…' : 'Start discovery'}
      onContinue={() => {
        const draft = readDraft();
        draft.name = name.trim();
        draft.description = description.trim();
        draft.cidrs = cidrs;
        draft.auths = auths;
        const choices = { ...readChoices(), rescan };
        writeDraft(draft);
        writeChoices(choices);
        setBusy(true);
        setError('');
        upsertPipeline(draft, discoveryRiver(draft, choices))
          .then((pipeline) => {
            markDiscovery(pipeline);
            navigate(`${PLUGIN_BASE_URL}/found`);
          })
          .catch((err: unknown) => {
            setError(err instanceof Error ? err.message : 'Fleet rejected the discovery config.');
          })
          .finally(() => setBusy(false));
      }}
      continueDisabled={!ready || busy}
    >
      {error && (
        <Alert title="Fleet" severity="error">
          {error}
        </Alert>
      )}
      <Field label="Name" invalid={!!nameError} error={nameError}>
        <Input value={name} onChange={(e) => setName(e.currentTarget.value)} width={40} />
      </Field>
      <Field
        label="Note for the next person"
        description="Kept with the group. Click ? for what a group is."
        invalid={!!noteError}
        error={noteError}
      >
        <Input value={description} onChange={(e) => setDescription(e.currentTarget.value)} width={60} />
      </Field>
      <p>
        Ranges <HelpButton id="cidr" />
      </p>
      <Field label="Ranges" description="One IPv4 CIDR per line." invalid={!!rangeError} error={rangeError}>
        <TextArea value={ranges} onChange={(e) => setRanges(e.currentTarget.value)} rows={4} />
      </Field>
      <p>
        Login <HelpButton id="authname" />
      </p>
      <Field
        label="Login nicknames"
        description="Nicknames only, matching the names in the credential file on the collector. Not the password or community string. Type one and press Enter. Tried in this order. The first one that answers is kept."
        invalid={!!authError}
        error={authError}
      >
        <MultiSelect
          width={40}
          allowCustomValue
          placeholder="public_v2"
          options={auths.map((name) => ({ label: name, value: name }))}
          value={auths}
          onChange={(items) => setAuths(items.map((item) => String(item.value ?? '')).filter(Boolean))}
        />
      </Field>
      <p>
        Look for new devices <HelpButton id="rescan" />
      </p>
      <Field
        label="How often"
        description="Daily sets discovery.snmp refresh_interval to 24h. Run once sets it to 8760h, about a year, because that block has no run-once switch. Edit refresh_interval in the collector config later for any other schedule."
      >
        <RadioButtonGroup
          options={[
            { label: 'Run once', value: 'once' },
            { label: 'Daily', value: 'daily' },
          ]}
          value={rescan ? 'daily' : 'once'}
          onChange={(value) => setRescan(value === 'daily')}
        />
      </Field>
      <p>Scanned by {initial.collectorId}. Change that on the previous step.</p>
    </HubFrame>
  );
}

export default GroupPage;
