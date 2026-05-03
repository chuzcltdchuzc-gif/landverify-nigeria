import { useState } from "react";
import { base44 } from "@/api/base44Client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { ShieldCheck, Scan, AlertTriangle, Loader2, CheckSquare, X, CheckCircle2, Clock } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { detectFraud, computeConfidence } from "@/lib/fraudDetection";
import ParcelCard from "@/components/dashboard/ParcelCard";
import VerificationPanel from "@/components/verify/VerificationPanel";
import { toast } from "sonner";

export default function Verify() {
  const [selectedParcel, setSelectedParcel] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [bulkSaving, setBulkSaving] = useState(false);
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
        await base44.entities.Parcel.update(r.id, {
          flags: r.detectedFlags,
          confidence_score: computeConfidence(r),
        });
        flaggedCount++;
      }
    }
    queryClient.invalidateQueries({ queryKey: ["parcels"] });
    setScanning(false);
    toast.success(`Scan complete. ${flaggedCount} parcel(s) flagged.`);
  };

  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    const allPending = pendingParcels.map((p) => p.id);
    setSelectedIds(new Set(allPending));
  };

  const clearSelection = () => {
    setSelectedIds(new Set());
    setSelectMode(false);
  };

  const bulkUpdate = async (status) => {
    if (selectedIds.size === 0) return;
    setBulkSaving(true);
    for (const id of selectedIds) {
      await base44.entities.Parcel.update(id, { status });
    }
    queryClient.invalidateQueries({ queryKey: ["parcels"] });
    setBulkSaving(false);
    toast.success(`${selectedIds.size} parcel(s) marked as ${status}.`);
    clearSelection();
  };

  const analyzed = detectFraud(parcels);
  const flaggedParcels = analyzed.filter((p) => p.detectedFlags.length > 0);
  const pendingParcels = parcels.filter((p) => p.status === "pending");

  return (
    <div className="p-4 pt-6">
      {/* Header */}
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
        <div className="flex gap-2">
          {!selectMode ? (
            <>
              <Button
                size="sm"
                variant="outline"
                className="gap-1.5"
                onClick={() => setSelectMode(true)}
                disabled={pendingParcels.length === 0}
              >
                <CheckSquare className="w-4 h-4" />
                Select
              </Button>
              <Button
                size="sm"
                className="gap-1.5"
                onClick={runFraudScan}
                disabled={scanning || parcels.length === 0}
              >
                {scanning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Scan className="w-4 h-4" />}
                Scan
              </Button>
            </>
          ) : (
            <Button size="sm" variant="ghost" onClick={clearSelection} className="gap-1.5">
              <X className="w-4 h-4" />
              Cancel
            </Button>
          )}
        </div>
      </div>

      {/* Bulk action bar */}
      {selectMode && (
        <div className="mb-4 p-3 bg-primary/5 border border-primary/20 rounded-xl flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-primary">
              {selectedIds.size} selected
            </span>
            <button
              className="text-xs text-muted-foreground underline"
              onClick={selectAll}
            >
              Select all ({pendingParcels.length})
            </button>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              className="h-8 gap-1.5 text-xs"
              onClick={() => bulkUpdate("verified")}
              disabled={selectedIds.size === 0 || bulkSaving}
            >
              {bulkSaving ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <CheckCircle2 className="w-3.5 h-3.5" />
              )}
              Verify
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1.5 text-xs border-accent/50 text-accent hover:bg-accent/10"
              onClick={() => bulkUpdate("under_review")}
              disabled={selectedIds.size === 0 || bulkSaving}
            >
              <Clock className="w-3.5 h-3.5" />
              Under Review
            </Button>
          </div>
        </div>
      )}

      {/* Flagged parcels */}
      {!selectMode && flaggedParcels.length > 0 && (
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

      {/* Pending parcels */}
      <div>
        <h2 className="text-sm font-semibold text-muted-foreground mb-3">
          Pending Review ({pendingParcels.length})
        </h2>
        <div className="space-y-3">
          {isLoading
            ? Array(3).fill(0).map((_, i) => <Skeleton key={i} className="h-28 rounded-lg" />)
            : pendingParcels.map((p) => (
                <ParcelCard
                  key={p.id}
                  parcel={p}
                  onClick={setSelectedParcel}
                  selectable={selectMode}
                  selected={selectedIds.has(p.id)}
                  onSelect={toggleSelect}
                />
              ))}
          {!isLoading && pendingParcels.length === 0 && (
            <p className="text-center text-muted-foreground py-8 text-sm">
              No parcels pending review.
            </p>
          )}
        </div>
      </div>

      {selectedParcel && !selectMode && (
        <VerificationPanel
          parcel={selectedParcel}
          onClose={() => setSelectedParcel(null)}
        />
      )}
    </div>
  );
}