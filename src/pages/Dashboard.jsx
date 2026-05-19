import { useState } from "react";
import { base44 } from "@/api/base44Client";
import { useQuery } from "@tanstack/react-query";
import { LayoutDashboard, MapPin, ShieldCheck, AlertTriangle, List, Map } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import ParcelCard from "@/components/dashboard/ParcelCard";
import ExportButtons from "@/components/dashboard/ExportButtons";
import ParcelMap from "@/components/dashboard/ParcelMap";
import RevenueEstimate from "@/components/dashboard/RevenueEstimate";
import ParcelDetailView from "@/components/dashboard/ParcelDetailView";
import { Skeleton } from "@/components/ui/skeleton";
import { useRole } from "@/lib/useRole";
import AccessDenied from "@/components/common/AccessDenied";

export default function Dashboard() {
  const [view, setView] = useState("list");
  const [selectedParcel, setSelectedParcel] = useState(null);
  const { canViewDashboard, isGovernment } = useRole();
  const { data: parcels = [], isLoading } = useQuery({
    queryKey: ["parcels"],
    queryFn: () => base44.entities.Parcel.list("-created_date"),
  });

  const stats = {
    total: parcels.length,
    pending: parcels.filter((p) => p.status === "pending").length,
    verified: parcels.filter((p) => p.status === "verified").length,
    flagged: parcels.filter((p) => p.flags?.length > 0).length,
  };

  if (!canViewDashboard) return <AccessDenied />;

  const statCards = [
    { label: "Total Parcels", value: stats.total, icon: MapPin, color: "text-primary" },
    { label: "Pending", value: stats.pending, icon: LayoutDashboard, color: "text-accent" },
    { label: "Verified", value: stats.verified, icon: ShieldCheck, color: "text-primary" },
    { label: "Flagged", value: stats.flagged, icon: AlertTriangle, color: "text-destructive" },
  ];

  return (
    <div className="p-4 pt-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-bold text-foreground">Dashboard</h1>
        <ExportButtons parcels={parcels} />
      </div>

      {isGovernment && <RevenueEstimate parcels={parcels} />}

      <div className="grid grid-cols-2 gap-3 mb-6">
        {statCards.map(({ label, value, icon: Icon, color }) => (
          <Card key={label}>
            <CardContent className="p-3 flex items-center gap-3">
              <div className={`w-9 h-9 rounded-lg bg-muted flex items-center justify-center ${color}`}>
                <Icon className="w-4 h-4" />
              </div>
              <div>
                <p className="text-xl font-bold text-foreground">{isLoading ? "-" : value}</p>
                <p className="text-[10px] text-muted-foreground">{label}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-muted-foreground">All Submissions</h2>
        <div className="flex bg-muted rounded-lg p-0.5 gap-0.5">
          <button
            onClick={() => setView("list")}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
              view === "list" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground"
            }`}
          >
            <List className="w-3.5 h-3.5" /> List
          </button>
          <button
            onClick={() => setView("map")}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
              view === "map" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground"
            }`}
          >
            <Map className="w-3.5 h-3.5" /> Map
          </button>
        </div>
      </div>

      {view === "map" ? (
        <ParcelMap parcels={parcels} />
      ) : (
        <div className="space-y-3">
          {isLoading
            ? Array(3).fill(0).map((_, i) => <Skeleton key={i} className="h-28 rounded-lg" />)
            : parcels.map((p) => <ParcelCard key={p.id} parcel={p} onClick={setSelectedParcel} />)}
          {!isLoading && parcels.length === 0 && (
            <div className="text-center text-muted-foreground py-12">
              No parcels captured yet. Go to Capture to add one.
            </div>
          )}
        </div>
      )}

      {selectedParcel && (
        <ParcelDetailView parcel={selectedParcel} onClose={() => setSelectedParcel(null)} />
      )}
    </div>
  );
}