import React from 'react';
import { Route, Routes } from 'react-router-dom';
import { STEPS } from '../../constants';
import HubStep from '../../pages/HubStep';

function App() {
  return (
    <Routes>
      {STEPS.slice(1).map((step) => (
        <Route key={step.id} path={step.id} element={<HubStep id={step.id} />} />
      ))}
      <Route path="*" element={<HubStep id="collector" />} />
    </Routes>
  );
}

export default App;
