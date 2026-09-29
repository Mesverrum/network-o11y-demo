import React from 'react';
import { Alert } from '@grafana/ui';
import { HubFrame } from '../components/HubFrame';
import { appliedName, readChoices, readDraft } from '../fleet';

function ReceivingPage() {
  const draft = readDraft();
  const choices = readChoices();
  const applied = appliedName();
  const rows: Array<[string, string]> = [
    ['Health and traffic', applied ? 'The collector picks this up within a minute.' : 'Waiting for Apply.'],
    ['Names and errors', applied ? 'Arriving every 5 minutes.' : 'Waiting for Apply.'],
    ['Neighbor topology', choices.neighbors ? 'Chosen. Not sent in this apply yet.' : 'Off'],
    ['Alarms', choices.traps ? 'Listening on port 1620 once the listener is on the collector.' : 'Off'],
    ['Device logs', choices.syslog ? 'Listening on port 1514 once the listener is on the collector.' : 'Off'],
    ['NetFlow and IPFIX', choices.netflow ? 'Listening on port 2055 once that listener is on the collector.' : 'Off'],
    ['sFlow', choices.sflow ? 'Listening on its own port once that listener is on the collector.' : 'Off'],
  ];

  return (
    <HubFrame
      stepId="receiving"
      title="Receiving"
      helpId="listening"
      intro="This is the end of discovery. Listening means the collector is ready and waiting for the device to send. Devices you come back to live in their own app."
      continueLabel="Open devices"
      onContinue={() => {
        window.location.assign('/a/mesverrum-networkdevices-app');
      }}
    >
      {applied ? (
        <Alert title="Fleet has the group" severity="success">
          {`${applied} is on ${draft.collectorId}. The note comes back as discovery_snmp_group_info in marcnetterfield1.`}
        </Alert>
      ) : (
        <Alert title="Not applied yet" severity="warning">
          Go back to Apply. Nothing is being polled for this group until you do.
        </Alert>
      )}
      <table>
        <thead>
          <tr>
            <th>What</th>
            <th>Now</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[0]}>
              <td>{row[0]}</td>
              <td>{row[1]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </HubFrame>
  );
}

export default ReceivingPage;
