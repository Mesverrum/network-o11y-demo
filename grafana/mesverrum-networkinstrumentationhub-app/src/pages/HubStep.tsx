import React from 'react';
import { PluginPage } from '@grafana/runtime';
import { STEPS } from '../constants';

function HubStep({ id }: { id: string }) {
  const step = STEPS.find((s) => s.id === id) ?? STEPS[0];
  return (
    <PluginPage>
      <h3>{step.title}</h3>
      <p>{step.body}</p>
    </PluginPage>
  );
}

export default HubStep;
