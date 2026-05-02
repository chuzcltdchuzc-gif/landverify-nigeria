import { useState } from "react";
import { base44 } from "@/api/base44Client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ShieldCheck, Scan, AlertTriangle, Loader2 } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { detectFraud, computeConfidence } from "@/lib/fraudDetection";
import ParcelCard from "@/components/dashboard/ParcelCard";
import VerificationPanel from "@/components/verify/VerificationPanel";
import { toast } from "sonner";

export default function Verify() {
  const [selectedParcel, setSelectedParcel] = useState(null);
  const [scanning, setScanning] = useState(false);
  const queryClient = useQueryClient();

  const { data: parcels = [], isLoading } = useQuery({
    queryKey: ["parcels"],
    queryFn: () => base44.entities.Parcel.list("-created_date"),
  });

  const runFraudScan = async () => {
    setScanning(true);
    const results = detectFraud(parcels);
    
    let flaggedCount = 0;
    for (const r of results) {
      if (r.detectedFlags.length > 0) {
        const score = computeConfidence(r);
        await base44.entities.Parcel.update(r.id, {
          flags: r.detectedFlags,
          confidence_score: score,
        });
        flaggedCount++;
      }
    }

    queryClient.invalidateQueries({ queryKey: ["parcels"] });
    setScanning(false);
    toast.success(`Scan complete. ${flaggedCount} parcel(s) flagged.`);
  };

  const analyzed = detectFraud(parcels);
  const flaggedParcels = analyzed.filter((p) => p.detectedFlags.length > 0);
  const pendingParcels = parcels.filter((p) => p.status === "pending");

  return (
    <div className="p-4 pt-6">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
            <ShieldCheck className="w-5 h-5 text-primary-foreground" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-foreground leading-tight">Verification</h1>
            <p className="text-xs text-muted-foreground">Fraud detection & review</p>
          </div>
        </div>
        <Button
          size="sm"
          className="gap-1.5"
          onClick={runFraudScan}
          disabled={scanning || parcels.length === 0}
        >
          {scanning ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Scan className="w-4 h-4" />
          )}
          Scan
        </Button>
      </div>

      {flaggedParcels.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="w-4 h-4 text-destructive" />
            <h2 className="text-sm font-semibold text-destructive">
              Flagged ({flaggedParcels.length})
            </h2>
          </div>
          <div className="space-y-3">
            {flaggedParcels.map((p) => (
              <ParcelCard key={p.id} parcel={p} onClick={setSelectedParcel} />
            ))}
          </div>
        </div>
      )}

      <div>
        <h2 className="text-sm font-semibold text-muted-foreground mb-3">
          Pending Review ({pendingParcels.length})
        </h2>
        <div className="space-y-3">
          {isLoading
            ? Array(3)
                .fill(0)
                .map((_, i) => <Skeleton key={i} className="h-28 rounded-lg" />)
            : pendingParcels.map((p) => (
                <ParcelCard key={p.id} parcel={p} onClick={setSelectedParcel} />
              ))}
          {!isLoading && pendingParcels.length === 0 && (
            <p className="text-center text-muted-foreground py-8 text-sm">
              No parcels pending review.
            </p>
          )}
        </div>
      </div>

      {selectedParcel && (
        <VerificationPanel
          parcel={selectedParcel}
          onClose={() => setSelectedParcel(null)}
        />
      )}
    </div>
  );
}