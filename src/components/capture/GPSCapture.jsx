import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Locate, Loader2, MapPin } from "lucide-react";

export default function GPSCapture({ latitude, longitude, onCapture }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleCapture = () => {
    if (!navigator.geolocation) {
      setError("GPS not supported on this device");
      return;
    }
    setLoading(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        onCapture(pos.coords.latitude, pos.coords.longitude);
        setLoading(false);
      },
      (err) => {
        setError("Could not get location. Please enable GPS.");
        setLoading(false);
      },
      { enableHighAccuracy: true, timeout: 15000 }
    );
  };

  const hasLocation = latitude !== null && longitude !== null;

  return (
    <div className="space-y-2">
      <label className="text-sm font-medium text-foreground">
        GPS Location <span className="text-destructive">*</span>
      </label>
      <Button
        type="button"
        variant={hasLocation ? "outline" : "default"}
        className="w-full h-14 text-base gap-2"
        onClick={handleCapture}
        disabled={loading}
      >
        {loading ? (
          <>
            <Loader2 className="w-5 h-5 animate-spin" />
            Getting location...
          </>
        ) : hasLocation ? (
          <>
            <MapPin className="w-5 h-5 text-primary" />
            {latitude.toFixed(6)}, {longitude.toFixed(6)}
          </>
        ) : (
          <>
            <Locate className="w-5 h-5" />
            Tap to Capture GPS
          </>
        )}
      </Button>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}