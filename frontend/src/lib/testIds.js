// Centralised test ids — keep names kebab-case
export const TID = {
    // Landing / auth
    googleLogin: 'google-login-btn',
    landingHero: 'landing-hero',
    landingPricing: 'landing-pricing',
    landingVerifyCta: 'landing-verify-cta',
    devLoginCitizen: 'dev-login-citizen',
    devLoginValidator: 'dev-login-validator',
    devLoginSurveyor: 'dev-login-surveyor',
    devLoginAdmin: 'dev-login-admin',
    logoutBtn: 'logout-btn',

    // Public verify
    verifyInput: 'verify-parcel-input',
    verifyBtn: 'verify-parcel-btn',
    verifyResult: 'verify-result',

    // Citizen
    citizenDashboard: 'citizen-dashboard',
    kpiMyParcels: 'kpi-my-parcels',
    kpiEvidence: 'kpi-evidence-uploaded',
    kpiAttestations: 'kpi-attestations',
    kpiTrust: 'kpi-trust-score',
    createParcelBtn: 'create-parcel-btn',
    parcelForm: 'parcel-create-form',
    parcelCommunity: 'parcel-input-community',
    parcelWard: 'parcel-input-ward',
    parcelLga: 'parcel-input-lga',
    parcelState: 'parcel-input-state',
    parcelSubmit: 'parcel-submit-btn',
    parcelRow: 'parcel-row',
    uploadEvidenceBtn: 'upload-evidence-btn',
    evidenceForm: 'evidence-form',
    evidenceType: 'evidence-type-select',
    evidenceFileName: 'evidence-file-name',
    evidenceFileUrl: 'evidence-file-url',
    evidenceSubmit: 'evidence-submit-btn',
    buyCreditsBtn: 'buy-credits-btn',
    creditPack: (code) => `credit-pack-${code}`,
    creditCheckout: (code) => `credit-checkout-${code}`,

    // Validator
    validatorDashboard: 'validator-dashboard',
    attestationForm: 'attestation-form',
    attestationParcelSelect: 'attestation-parcel-select',
    attestationRole: 'attestation-role-select',
    attestationStatement: 'attestation-statement',
    attestationRelationship: 'attestation-relationship',
    attestationYears: 'attestation-years',
    attestationSubmit: 'attestation-submit-btn',

    // Surveyor
    surveyorDashboard: 'surveyor-dashboard',
    surveyUploadForm: 'survey-upload-form',
    surveyParcelSelect: 'survey-parcel-select',
    surveyPlanUrl: 'survey-plan-url',
    surveyNotes: 'survey-notes',
    surveySubmit: 'survey-submit-btn',

    // Admin
    adminDashboard: 'admin-dashboard',
    adminRunTrust: 'admin-run-trust',
    adminProcessJobs: 'admin-process-jobs',
    adminSecurityScan: 'admin-security-scan',
    adminApproveEvidence: (id) => `approve-evidence-${id}`,
    adminTabOverview: 'admin-tab-overview',
    adminTabUsers: 'admin-tab-users',
    adminTabParcels: 'admin-tab-parcels',
    adminTabEvidence: 'admin-tab-evidence',
    adminTabJobs: 'admin-tab-jobs',
    adminTabTrust: 'admin-tab-trust',
    adminTabSecurity: 'admin-tab-security',
};
