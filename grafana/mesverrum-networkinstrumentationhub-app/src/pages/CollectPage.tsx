import React, { useState } from 'react';
import { css } from '@emotion/css';
import { GrafanaTheme2 } from '@grafana/data';
import { RadioButtonGroup, useStyles2 } from '@grafana/ui';
import { useNavigate } from 'react-router-dom';
import { HelpButton, HubFrame } from '../components/HubFrame';
import { PLUGIN_BASE_URL } from '../constants';
import { CollectChoices, LISTEN, readChoices, writeChoices } from '../fleet';

type ChoiceKey = 'neighbors' | 'traps' | 'syslog' | 'netflow' | 'sflow';

const POLLED: Array<{ key: ChoiceKey; title: string; detail: string; help: string }> = [
  {
    key: 'neighbors',
    title: 'Neighbor topology',
    detail: 'What is plugged into each port, so Grafana can draw the links between devices.',
    help: 'neighbors',
  },
];

const LISTENING: Array<{ key: ChoiceKey; title: string; detail: string; help: string }> = [
  {
    key: 'traps',
    title: 'Alarms (SNMP traps)',
    detail: `Instant alarms from the device, like a port going down. Point the device at UDP ${LISTEN.traps}.`,
    help: 'traps',
  },
  {
    key: 'syslog',
    title: 'Device logs (syslog)',
    detail: `A copy of the device’s running log. Point the device at UDP ${LISTEN.syslog}.`,
    help: 'syslog',
  },
  {
    key: 'netflow',
    title: 'NetFlow and IPFIX',
    detail: `Who talked to whom. v5, v9, and IPFIX share one listener. Point the device at UDP ${LISTEN.netflow}.`,
    help: 'netflow',
  },
  {
    key: 'sflow',
    title: 'sFlow',
    detail: `The same kind of record, in a different format. It needs its own listener. Point the device at UDP ${LISTEN.sflow}.`,
    help: 'sflow',
  },
];

const ON_OFF = [
  { label: 'On', value: 'on' },
  { label: 'Off', value: 'off' },
];

function CollectPage() {
  const navigate = useNavigate();
  const styles = useStyles2(getStyles);
  const [choices, setChoices] = useState<CollectChoices>(readChoices());
  const set = (key: ChoiceKey, value: string) => setChoices({ ...choices, [key]: value === 'on' });

  return (
    <HubFrame
      stepId="collect"
      title="What to collect"
      helpId="whosends"
      intro="Device health, traffic, port names, and errors are always collected. Choose the extras. Below the line, the device has to be pointed at the collector."
      onContinue={() => {
        writeChoices(choices);
        navigate(`${PLUGIN_BASE_URL}/apply`);
      }}
    >
      <h4 className={styles.section}>Collector asks</h4>
      <p className={styles.quiet}>
        The collector reaches out. These start after Apply. <HelpButton id="basics" />
      </p>
      {POLLED.map((row) => (
        <div key={row.key} className={styles.row}>
          <RadioButtonGroup
            size="sm"
            options={ON_OFF}
            value={choices[row.key] ? 'on' : 'off'}
            onChange={(value) => set(row.key, value)}
          />
          <div>
            <div className={styles.title}>
              <strong>{row.title}</strong>
              <HelpButton id={row.help} />
            </div>
            <p className={styles.quiet}>{row.detail}</p>
          </div>
        </div>
      ))}

      <h4 className={styles.divider}>Device sends</h4>
      <p className={styles.quiet}>
        The collector only listens. Someone still has to point each device at it. <HelpButton id="ports" />
      </p>
      {LISTENING.map((row) => (
        <div key={row.key} className={styles.row}>
          <RadioButtonGroup
            size="sm"
            options={ON_OFF}
            value={choices[row.key] ? 'on' : 'off'}
            onChange={(value) => set(row.key, value)}
          />
          <div>
            <div className={styles.title}>
              <strong>{row.title}</strong>
              <HelpButton id={row.help} />
            </div>
            <p className={styles.quiet}>{row.detail}</p>
          </div>
        </div>
      ))}
    </HubFrame>
  );
}

const getStyles = (theme: GrafanaTheme2) => ({
  section: css`
    margin-bottom: 0;
  `,
  divider: css`
    margin: ${theme.spacing(2)} 0 0;
    padding-top: ${theme.spacing(2)};
    border-top: 2px solid ${theme.colors.border.medium};
  `,
  row: css`
    display: grid;
    grid-template-columns: 140px minmax(0, 1fr);
    gap: ${theme.spacing(2)};
    align-items: center;
    padding: ${theme.spacing(1.5)} 0;
    border-top: 1px solid ${theme.colors.border.weak};
  `,
  title: css`
    display: flex;
    align-items: center;
    gap: ${theme.spacing(1)};
  `,
  quiet: css`
    color: ${theme.colors.text.secondary};
    margin: 0;
  `,
});

export default CollectPage;
