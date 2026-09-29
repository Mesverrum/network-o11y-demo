import React, { useEffect, useState } from 'react';
import { Alert, Badge, BadgeColor, LinkButton } from '@grafana/ui';
import { HubFrame } from '../components/HubFrame';
import {
  CheckState,
  DASHBOARDS,
  LiveCheck,
  appliedName,
  dashboardUrl,
  liveChecks,
  readChoices,
  readDraft,
} from '../fleet';

const POLL_MS = 15000;

const BADGE: Record<CheckState, { text: string; color: BadgeColor }> = {
  ok: { text: 'Receiving', color: 'green' },
  waiting: { text: 'Waiting', color: 'blue' },
  problem: { text: 'Check this', color: 'red' },
  off: { text: 'Off', color: 'darkgrey' as BadgeColor },
};

function ReceivingPage() {
  const draft = readDraft();
  const choices = readChoices();
  const applied = appliedName();
  const [checks, setChecks] = useState<LiveCheck[]>([]);
  const [error, setError] = useState('');
  const [updated, setUpdated] = useState('');

  useEffect(() => {
    let cancel = false;
    const run = () =>
      liveChecks(draft, choices)
        .then((rows) => {
          if (!cancel) {
            setChecks(rows);
            setError('');
            setUpdated(new Date().toLocaleTimeString());
          }
        })
        .catch((err: unknown) => {
          if (!cancel) {
            setError(err instanceof Error ? err.message : 'The stack did not answer.');
          }
        });
    run();
    const timer = window.setInterval(run, POLL_MS);
    return () => {
      cancel = true;
      window.clearInterval(timer);
    };
    // The draft lives in sessionStorage and does not change while this page is open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const listeners: Array<[string, boolean]> = [
    ['Alarms (traps, port 1620)', choices.traps],
    ['Device logs (syslog, port 1514)', choices.syslog],
    ['NetFlow and IPFIX (port 2055)', choices.netflow],
    ['sFlow', choices.sflow],
  ];

  return (
    <HubFrame
      stepId="receiving"
      title="Receiving"
      helpId="listening"
      intro={`Live from the stack ${draft.collectorId} writes to. Refreshes every 15 seconds.`}
      continueLabel="Open devices"
      onContinue={() => {
        window.location.assign('/a/mesverrum-networkdevices-app');
      }}
    >
      {!applied && (
        <Alert title="Not applied in this browser" severity="info">
          {`This page still reads live data for ${draft.name} on ${draft.collectorId}. Apply from this browser to change what it polls.`}
        </Alert>
      )}
      {error && (
        <Alert title="Could not read the stack" severity="error">
          {error}
        </Alert>
      )}
      <table style={{ width: '100%' }}>
        <thead>
          <tr>
            <th>What</th>
            <th>Now</th>
            <th>Detail</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {checks.map((check) => (
            <tr key={check.id}>
              <td>{check.label}</td>
              <td>
                <Badge text={BADGE[check.state].text} color={BADGE[check.state].color} />
              </td>
              <td>{check.detail}</td>
              <td>
                <LinkButton size="sm" variant="secondary" fill="text" href={dashboardUrl(check.dashboard, draft)}>
                  Dashboard
                </LinkButton>
              </td>
            </tr>
          ))}
          {listeners.map(([label, on]) => (
            <tr key={label}>
              <td>{label}</td>
              <td>
                <Badge text={on ? 'Not in pipeline' : 'Off'} color={on ? 'orange' : ('darkgrey' as BadgeColor)} />
              </td>
              <td>{on ? 'Chosen. This Apply does not add the listener yet.' : 'Off'}</td>
              <td />
            </tr>
          ))}
        </tbody>
      </table>
      <p>{updated ? `Updated ${updated}.` : 'Reading…'}</p>
      <div style={{ display: 'flex', gap: 8 }}>
        <LinkButton variant="secondary" href={dashboardUrl(DASHBOARDS.rollout, draft)}>
          Fleet rollout
        </LinkButton>
        <LinkButton variant="secondary" href={dashboardUrl(DASHBOARDS.discovery, draft)}>
          Discovery
        </LinkButton>
        <LinkButton variant="secondary" href={dashboardUrl(DASHBOARDS.arriving, draft)}>
          Data arriving
        </LinkButton>
      </div>
    </HubFrame>
  );
}

export default ReceivingPage;
