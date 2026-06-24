import axios from 'axios';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({
    baseURL: API,
    withCredentials: true,
});

// Fall back to bearer token in localStorage when cookies are blocked
api.interceptors.request.use((config) => {
    const token = localStorage.getItem('lv_session_token');
    if (token) {
        config.headers = config.headers || {};
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

export const NGN = (amount) => new Intl.NumberFormat('en-NG', {
    style: 'currency', currency: 'NGN', maximumFractionDigits: 0,
}).format(amount || 0);

export const formatDate = (iso) => {
    if (!iso) return '—';
    try { return new Date(iso).toLocaleString('en-NG', { dateStyle: 'medium', timeStyle: 'short' }); }
    catch { return iso; }
};

export const statusColor = (status) => {
    const map = {
        VERIFIED: 'bg-emerald-100 text-emerald-800 border-emerald-300',
        APPROVED: 'bg-emerald-100 text-emerald-800 border-emerald-300',
        COMPLETED: 'bg-emerald-100 text-emerald-800 border-emerald-300',
        PENDING: 'bg-amber-100 text-amber-800 border-amber-300',
        PROCESSING: 'bg-sky-100 text-sky-800 border-sky-300',
        UNVERIFIED: 'bg-slate-100 text-slate-700 border-slate-300',
        DISPUTED: 'bg-rose-100 text-rose-800 border-rose-300',
        FAILED: 'bg-rose-100 text-rose-800 border-rose-300',
        FROZEN: 'bg-rose-100 text-rose-800 border-rose-300',
        ACTIVE: 'bg-emerald-100 text-emerald-800 border-emerald-300',
        ISSUED: 'bg-emerald-100 text-emerald-800 border-emerald-300',
        OK: 'bg-emerald-100 text-emerald-800 border-emerald-300',
        WARN: 'bg-amber-100 text-amber-800 border-amber-300',
    };
    return map[status] || 'bg-slate-100 text-slate-700 border-slate-300';
};
