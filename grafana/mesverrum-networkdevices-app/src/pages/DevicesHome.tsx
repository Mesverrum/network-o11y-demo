import React from 'react';
import { PluginPage } from '@grafana/runtime';
import { Button } from '@grafana/ui';

const WIZARD = '/a/mesverrum-networkinstrumentationhub-app/collector';

function DevicesHome() {
  return (
    <PluginPage>
      <h2>Network devices</h2>
      <p>
        This is the app you come back to. Open one device, or change several together. Discovery stays in the
        Instrumentation Hub.
      </p>
      <p>The collector has not reported a device list here yet. Pause and move are not sent to the collector yet.</p>
      <Button onClick={() => window.location.assign(WIZARD)}>Open the discovery wizard</Button>
    </PluginPage>
  );
}

export default DevicesHome;
