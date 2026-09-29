import React, { useState } from 'react';
import { Alert } from '@grafana/ui';
import { useNavigate } from 'react-router-dom';
import { HubFrame } from '../components/HubFrame';
import { PLUGIN_BASE_URL } from '../constants';
import {
  appliedName,
  fleetCall,
  FleetPipeline,
  markApplied,
  pipelineName,
  pipelineRiver,
  discoveryName,
  readChoices,
  LISTEN,
  readDraft,
  riverRevision,
  validateDraft,
} from '../fleet';

function ApplyPage() {
  const navigate = useNavigate();
  const draft = readDraft();
  const choices = readChoices();
  const problem = validateDraft(draft);
  const river = problem ? '' : pipelineRiver(draft, choices);
  const [result, setResult] = useState(appliedName());
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const name = pipelineName(draft.name);

  const apply = () => {
    if (problem) {
      return;
    }
    setBusy(true);
    setError('');
    fleetCall<{ pipeline?: FleetPipeline }>('pipeline.v1.PipelineService/UpsertPipeline', {
      pipeline: {
        name,
        contents: river,
        matchers: [`collector.ID="${draft.collectorId}"`],
        enabled: true,
      },
    })
      .then(() => {
        markApplied(name, riverRevision(river));
        setResult(name);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Fleet rejected the pipeline.');
      })
      .finally(() => setBusy(false));
  };

  return (
    <HubFrame
      stepId="apply"
      title="Apply"
      helpId="apply"
      intro={
        result
          ? `Fleet accepted ${result}. See what's arriving next. The collector polls about once a minute.`
          : discoveryName()
          ? `Discovery for ${discoveryName()} is already running. Apply adds health polling on top of that scan.`
          : 'Nothing is written yet. This is what will be sent to that one collector.'
      }
      continueLabel={result ? "See what's arriving" : busy ? 'Applying…' : 'Apply to Fleet'}
      continueDisabled={Boolean(problem) || busy}
      onContinue={() => {
        if (result) {
          navigate(`${PLUGIN_BASE_URL}/receiving`);
          return;
        }
        apply();
      }}
    >
      {problem && (
        <Alert title="Go back to Add a group" severity="warning">
          That page still has a field to fix. Apply stays off until it is.
        </Alert>
      )}
      {error && (
        <Alert title="Fleet" severity="error">
          {error}
        </Alert>
      )}
      {result && (
        <Alert title="Applied" severity="success">
          {`Fleet accepted ${result}. Next, see what is arriving. The collector polls about once a minute.`}
        </Alert>
      )}
      <ul>
        <li>{`Watch group ${draft.name} on ${draft.collectorId}. Other collectors stay as they are.`}</li>
        {draft.description && <li>{`Note kept with the group: ${draft.description}`}</li>}
        <li>{`Ranges ${draft.cidrs.join(', ') || 'none'}. Logins, in try order: ${draft.auths.join(', ') || 'none'}.`}</li>
        <li>Health and traffic every minute. Names and errors every 5 minutes.</li>
        <li>{choices.neighbors ? 'Neighbor topology on.' : 'Neighbor topology off.'}</li>
        <li>{draft.ignores.length ? `Ignored addresses: ${draft.ignores.join(', ')}.` : 'No addresses ignored.'}</li>
        <li>{choices.traps ? `Alarms listen on UDP ${LISTEN.traps}. Point each device at the collector.` : 'Alarms off.'}</li>
        <li>{choices.syslog ? `Device logs listen on UDP ${LISTEN.syslog}.` : 'Device logs off.'}</li>
        <li>{choices.netflow ? `NetFlow and IPFIX listen on UDP ${LISTEN.netflow}.` : 'NetFlow and IPFIX off.'}</li>
        <li>{choices.sflow ? `sFlow listens on UDP ${LISTEN.sflow}.` : 'sFlow off.'}</li>
      </ul>
      {river && (
        <details>
          <summary>Show the settings Fleet will receive</summary>
          <pre style={{ whiteSpace: 'pre-wrap' }}>{river}</pre>
        </details>
      )}
    </HubFrame>
  );
}

export default ApplyPage;
