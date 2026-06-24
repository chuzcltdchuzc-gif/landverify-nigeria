import React from 'react';
import { Disclaimer } from './AppShell.jsx';
import { Link } from 'react-router-dom';

export default function Footer() {
    return (
        <footer className="border-t border-[#2e7d52]/10 bg-white/60 backdrop-blur-xl mt-12">
            <div className="max-w-[1400px] mx-auto px-6 py-8 grid md:grid-cols-3 gap-6">
                <div>
                    <div className="font-display text-lg text-[#1a2e1a]">Aquasavannah LandVault</div>
                    <p className="text-sm text-[#546e7a] mt-2">
                        The evidence layer for Nigerian land. Preserve. Verify. Trust.
                    </p>
                </div>
                <div className="text-sm">
                    <div className="font-display text-[#1a2e1a] mb-2">Platform</div>
                    <ul className="space-y-1 text-[#546e7a]">
                        <li><Link to="/verify" className="hover:text-[#2e7d52]">Public Verification</Link></li>
                        <li><Link to="/trust" className="hover:text-[#2e7d52]">Trust Architecture</Link></li>
                        <li><Link to="/community-transparency" className="hover:text-[#2e7d52]">Community Transparency</Link></li>
                        <li><Link to="/billing" className="hover:text-[#2e7d52]">Plans &amp; Credits</Link></li>
                    </ul>
                </div>
                <div>
                    <div className="font-display text-[#1a2e1a] mb-2 text-sm">Legal Disclaimer</div>
                    <Disclaimer />
                </div>
            </div>
            <div className="border-t border-[#2e7d52]/10 py-3 text-center text-xs text-[#546e7a] font-mono">
                © 2026 AQUASAVANNAH · LANDVAULT · NG-PILOT
            </div>
        </footer>
    );
}
