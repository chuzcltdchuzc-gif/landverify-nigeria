import React from 'react';
import '@/App.css';
import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom';
import { Toaster } from 'sonner';
import { AuthProvider } from './lib/auth.jsx';
import Landing from './pages/Landing.jsx';
import AuthCallback from './pages/AuthCallback.jsx';
import PublicVerify from './pages/PublicVerify.jsx';
import Trust from './pages/Trust.jsx';
import CommunityTransparency from './pages/CommunityTransparency.jsx';
import CitizenDashboard from './pages/CitizenDashboard.jsx';
import ValidatorDashboard from './pages/ValidatorDashboard.jsx';
import SurveyorDashboard from './pages/SurveyorDashboard.jsx';
import AdminDashboard from './pages/AdminDashboard.jsx';
import Billing, { BillingSuccess, BillingCancel, PaystackSuccess } from './pages/Billing.jsx';
import ProtectedRoute from './components/ProtectedRoute.jsx';
import EvidenceWorkspace from './pages/evidence/EvidenceWorkspace.jsx';
import EvidenceList from './pages/evidence/EvidenceList.jsx';
import EvidenceUpload from './pages/evidence/EvidenceUpload.jsx';
import EvidenceDetail, {
    OverviewTab,
    TimelineTab,
    CustodyTab,
    SealTab,
    IntegrityTab,
    VersionsTab,
    LegalHoldTab,
} from './pages/evidence/EvidenceDetail.jsx';
import ProjectionsAdmin from './pages/evidence/ProjectionsAdmin.jsx';

function Router() {
    const location = useLocation();
    if (location.hash?.includes('session_id=')) return <AuthCallback />;
    return (
        <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/verify" element={<PublicVerify />} />
            <Route path="/trust" element={<Trust />} />
            <Route path="/community-transparency" element={<CommunityTransparency />} />
            <Route path="/dashboard" element={<ProtectedRoute><CitizenDashboard /></ProtectedRoute>} />
            <Route path="/validator" element={<ProtectedRoute minRole="COMMUNITY_VALIDATOR"><ValidatorDashboard /></ProtectedRoute>} />
            <Route path="/surveyor" element={<ProtectedRoute minRole="SURVEYOR"><SurveyorDashboard /></ProtectedRoute>} />
            <Route path="/admin" element={<ProtectedRoute minRole="ADMIN"><AdminDashboard /></ProtectedRoute>} />
            <Route path="/admin/*" element={<ProtectedRoute minRole="ADMIN"><AdminDashboard /></ProtectedRoute>} />
            <Route path="/billing" element={<ProtectedRoute><Billing /></ProtectedRoute>} />
            <Route path="/billing/success" element={<ProtectedRoute><BillingSuccess /></ProtectedRoute>} />
            <Route path="/billing/cancel" element={<ProtectedRoute><BillingCancel /></ProtectedRoute>} />
            <Route path="/billing/paystack-success" element={<ProtectedRoute><PaystackSuccess /></ProtectedRoute>} />
            <Route path="/billing/paystack-callback" element={<ProtectedRoute><PaystackSuccess /></ProtectedRoute>} />
            {/* Phase 3.9 — Evidence bounded context UI (SDK-only) */}
            <Route path="/evidence" element={<EvidenceWorkspace />}>
                <Route index element={<EvidenceList />} />
                <Route path="upload" element={<EvidenceUpload />} />
                <Route path="admin/projections" element={<ProjectionsAdmin />} />
                <Route path="items/:evidenceId" element={<EvidenceDetail />}>
                    <Route index element={<OverviewTab />} />
                    <Route path="timeline" element={<TimelineTab />} />
                    <Route path="seal" element={<SealTab />} />
                    <Route path="integrity" element={<IntegrityTab />} />
                    <Route path="custody" element={<CustodyTab />} />
                    <Route path="versions" element={<VersionsTab />} />
                    <Route path="legal-holds" element={<LegalHoldTab />} />
                </Route>
            </Route>
        </Routes>
    );
}

export default function App() {
    return (
        <div className="App">
            <BrowserRouter>
                <AuthProvider>
                    <Router />
                    <Toaster position="top-right" richColors closeButton/>
                </AuthProvider>
            </BrowserRouter>
        </div>
    );
}
