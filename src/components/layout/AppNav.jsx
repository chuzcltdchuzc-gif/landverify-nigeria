import { Link, useLocation } from "react-router-dom";
import { MapPin, LayoutDashboard, ShieldCheck, BookOpen } from "lucide-react";
import { useRole } from "@/lib/useRole";

export default function AppNav() {
  const location = useLocation();
  const { canCapture, canVerify, canViewDashboard, canViewGuide } = useRole();

  const navItems = [
    canCapture && { path: "/", label: "Capture", icon: MapPin },
    canViewDashboard && { path: "/dashboard", label: "Data", icon: LayoutDashboard },
    canVerify && { path: "/verify", label: "Verify", icon: ShieldCheck },
    canViewGuide && { path: "/guide", label: "Guide", icon: BookOpen },
  ].filter(Boolean);

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 bg-card border-t border-border safe-area-bottom">
      <div className="flex justify-around items-center h-16 max-w-lg mx-auto">
        {navItems.map(({ path, label, icon: Icon }) => {
          const active = location.pathname === path;
          return (
            <Link
              key={path}
              to={path}
              className={`flex flex-col items-center gap-0.5 px-3 py-1.5 rounded-lg transition-colors ${
                active ? "text-primary" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon className="w-5 h-5" />
              <span className="text-[10px] font-medium">{label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}