import React, { createContext, useContext, useState } from 'react';
import { css } from '@emotion/css';
import { GrafanaTheme2 } from '@grafana/data';
import { PluginPage } from '@grafana/runtime';
import { Button, useStyles2 } from '@grafana/ui';
import { useNavigate } from 'react-router-dom';
import { PLUGIN_BASE_URL, STEPS } from '../constants';
import { HELP } from '../help';

const HelpContext = createContext({
  helpKey: '',
  setHelpKey: (_key: string) => {},
});

export function useHelp() {
  return useContext(HelpContext);
}

export function HelpButton({ id }: { id: string }) {
  const { setHelpKey } = useHelp();
  const entry = HELP[id];
  return (
    <Button
      size="sm"
      variant="secondary"
      icon="question-circle"
      aria-label={entry ? entry.title : 'Help'}
      onClick={() => setHelpKey(id)}
    >
      ?
    </Button>
  );
}

export function HubFrame({
  stepId,
  title,
  intro,
  helpId,
  children,
  onContinue,
  continueLabel,
  continueDisabled,
}: {
  stepId: string;
  title: string;
  intro: string;
  helpId?: string;
  children: React.ReactNode;
  onContinue?: () => void;
  continueLabel?: string;
  continueDisabled?: boolean;
}) {
  const styles = useStyles2(getStyles);
  const navigate = useNavigate();
  const [helpKey, setHelpKey] = useState(helpId || '');
  const index = STEPS.findIndex((step) => step.id === stepId);
  const previous = index > 0 ? STEPS[index - 1] : undefined;
  const next = index >= 0 && index < STEPS.length - 1 ? STEPS[index + 1] : undefined;
  const help = HELP[helpKey];

  const go = (id: string) => navigate(`${PLUGIN_BASE_URL}/${id}`);

  return (
    <HelpContext.Provider value={{ helpKey, setHelpKey }}>
      <PluginPage>
        <h2>Network Instrumentation Hub</h2>
        <p className={styles.quiet}>
          Pick a collector, tell it where to look, choose what to collect. Anything with a ? has a plain explanation on the right.
        </p>
        <div className={styles.steps}>
          {STEPS.map((step, i) => (
            <Button
              key={step.id}
              size="sm"
              variant={step.id === stepId ? 'primary' : 'secondary'}
              onClick={() => go(step.id)}
            >
              {`${i + 1}  ${step.title}`}
            </Button>
          ))}
        </div>
        <div className={styles.frame}>
          <div>
            <div className={styles.titleRow}>
              <h3>{title}</h3>
              {helpId && <HelpButton id={helpId} />}
            </div>
            <p>{intro}</p>
            {children}
            <div className={styles.footer}>
              <Button variant="secondary" disabled={!previous} onClick={() => previous && go(previous.id)}>
                Back
              </Button>
              {(onContinue || next) && (
                <Button
                  disabled={continueDisabled}
                  onClick={() => (onContinue ? onContinue() : next && go(next.id))}
                >
                  {continueLabel || (index === 4 ? 'Apply to Fleet' : 'Continue')}
                </Button>
              )}
            </div>
          </div>
          <aside className={styles.help}>
            {help ? (
              <>
                <div className={styles.titleRow}>
                  <h4>{help.title}</h4>
                  <Button size="sm" variant="secondary" onClick={() => setHelpKey('')}>
                    Close
                  </Button>
                </div>
                <p>{help.body}</p>
              </>
            ) : (
              <p className={styles.quiet}>Click any ? on the left and the explanation shows here.</p>
            )}
          </aside>
        </div>
      </PluginPage>
    </HelpContext.Provider>
  );
}

const getStyles = (theme: GrafanaTheme2) => ({
  quiet: css`
    color: ${theme.colors.text.secondary};
  `,
  steps: css`
    display: flex;
    flex-wrap: wrap;
    gap: ${theme.spacing(1)};
    margin-bottom: ${theme.spacing(2)};
  `,
  frame: css`
    display: grid;
    grid-template-columns: minmax(0, 1.6fr) minmax(220px, 0.7fr);
    gap: ${theme.spacing(3)};
    align-items: start;
    @media (max-width: 900px) {
      grid-template-columns: 1fr;
    }
  `,
  titleRow: css`
    display: flex;
    align-items: center;
    gap: ${theme.spacing(1)};
  `,
  footer: css`
    display: flex;
    justify-content: space-between;
    margin-top: ${theme.spacing(2)};
  `,
  help: css`
    border: 1px solid ${theme.colors.border.weak};
    border-radius: ${theme.shape.radius.default};
    padding: ${theme.spacing(2)};
  `,
});
