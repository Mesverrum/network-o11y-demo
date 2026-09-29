import React from 'react';
import { Route, Routes } from 'react-router-dom';
import CollectorPage from '../../pages/CollectorPage';
import GroupPage from '../../pages/GroupPage';
import FoundPage from '../../pages/FoundPage';
import CollectPage from '../../pages/CollectPage';
import ApplyPage from '../../pages/ApplyPage';
import ReceivingPage from '../../pages/ReceivingPage';

function App() {
  return (
    <Routes>
      <Route path="collector" element={<CollectorPage />} />
      <Route path="group" element={<GroupPage />} />
      <Route path="found" element={<FoundPage />} />
      <Route path="collect" element={<CollectPage />} />
      <Route path="apply" element={<ApplyPage />} />
      <Route path="receiving" element={<ReceivingPage />} />
      <Route path="*" element={<CollectorPage />} />
    </Routes>
  );
}

export default App;
