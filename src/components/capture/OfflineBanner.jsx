import { WifiOff, Wifi, CloudUpload, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function OfflineBanner({ isOnline, queueCount, onSync, syncing }) {
  if (isOnline && queueCount === 0) return null;

  return (
    <div
      className={`flex items-center justify-between gap-3 rounded-xl px-4 py-3 mb-4 text-sm font-medium ${
        isOnline
          ? "bg-primary/10 text-primary border border-primary/20"
          : "bg-destructive/10 text-destructive border border-destructive/20"
      }`}
    >
      <div className="flex items-center gap-2">
        {isOnline ? <Wifi className="w-4 h-4" /> : <WifiOff className="w-4 h-4" />}
        <span>
          {isOnline
            ? `Back online — ${queueCount} parcel${queueCount !== 1 ? "s" : ""} pending upload`
            : `Offline${queueCount > 0 ? ` — ${queueCount} saved locally` : " — data will be saved locally"}`}
        </span>
      </div>
      {isOnline && queueCount > 0 && (
        <Button size="sm" variant="outline" onClick={onSync} disabled={syncing} className="h-7 text-xs gap-1">
          {syncing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CloudUpload className="w-3.5 h-3.5" />}
          Sync
        </Button>
      )}
    </div>
  );
}