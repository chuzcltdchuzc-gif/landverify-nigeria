import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { CheckCircle2, XCircle, AlertTriangle, MapPin, Phone, Image } from "lucide-react";
import { base44 } from "@/api/base44Client";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { format } from "date-fns";
import { generateLandId } from "@/lib/generateLandId";

export default function VerificationPanel({ parcel, onClose }) {
  const [notes, setNotes] = useState(parcel.verification_notes || "");
  const [confidence, setConfidence] = useState(parcel.confidence_score || 50);
  const [saving, setSaving] = useState(false);
  const queryClient = useQueryClient();

  const save = async (status) => {
    setSaving(true);
    const updates = { status, verification_notes: notes, confidence_score: confidence };
    if (status === "verified" && !parcel.land_id) {
      updates.land_id = generateLandId();
    }
    await base44.entities.Parcel.update(parcel.id, updates);
    queryClient.invalidateQueries({ queryKey: ["parcels"] });
    setSaving(false);
    toast.success(`Parcel ${status}${updates.land_id ? ` · ID: ${updates.land_id}` : ""}`);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-end sm:items-center justify-center">
      <Card className="w-full max-w-lg max-h-[90vh] overflow-y-auto m-2 shadow-xl">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Verify Parcel</CardTitle>
            <Button variant="ghost" size="sm" onClick={onClose}>
              <XCircle className="w-4 h-4" />
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <h3 className="font-semibold text-lg">{parcel.owner_name}</h3>
            <div className="flex items-center gap-1 text-sm text-muted-foreground">
              <Phone className="w-3 h-3" />
              {parcel.phone}
            </div>
            <div className="flex items-center gap-1 text-sm text-muted-foreground mt-1">
              <MapPin className="w-3 h-3" />
              {parcel.latitude?.toFixed(6)}, {parcel.longitude?.toFixed(6)}
            </div>
            {parcel.captured_at && (
              <p className="text-xs text-muted-foreground mt-1">
                Captured: {format(new Date(parcel.captured_at), "dd MMM yyyy, HH:mm")}
              </p>
            )}
          </div>

          {parcel.description && (
            <p className="text-sm text-muted-foreground bg-muted p-3 rounded-lg">
              {parcel.description}
            </p>
          )}

          {parcel.photos?.length > 0 && (
            <div>
              <div className="flex items-center gap-1 text-sm font-medium mb-2">
                <Image className="w-3.5 h-3.5" />
                Photos ({parcel.photos.length})
              </div>
              <div className="flex gap-2 overflow-x-auto pb-2">
                {parcel.photos.map((url, i) => (
                  <img
                    key={i}
                    src={url}
                    alt={`Photo ${i + 1}`}
                    className="w-24 h-24 rounded-lg object-cover border border-border flex-shrink-0"
                  />
                ))}
              </div>
            </div>
          )}

          {(parcel.flags?.length > 0 || parcel.detectedFlags?.length > 0) && (
            <div className="space-y-1.5">
              <p className="text-sm font-medium text-destructive flex items-center gap-1">
                <AlertTriangle className="w-3.5 h-3.5" />
                Flags
              </p>
              <div className="flex flex-wrap gap-1">
                {(parcel.detectedFlags || parcel.flags || []).map((f, i) => (
                  <Badge key={i} variant="destructive" className="text-xs">
                    {f}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-2">
            <label className="text-sm font-medium">
              Confidence Score: <span className="text-primary font-bold">{confidence}</span>
            </label>
            <Slider
              value={[confidence]}
              onValueChange={([v]) => setConfidence(v)}
              max={100}
              step={1}
              className="w-full"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">Verification Notes</label>
            <Textarea
              placeholder="Add notes..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="min-h-[60px]"
            />
          </div>

          <div className="flex gap-2 pt-2">
            <Button
              className="flex-1 h-12 gap-1.5"
              onClick={() => save("verified")}
              disabled={saving}
            >
              <CheckCircle2 className="w-4 h-4" />
              Verify
            </Button>
            <Button
              variant="destructive"
              className="flex-1 h-12 gap-1.5"
              onClick={() => save("rejected")}
              disabled={saving}
            >
              <XCircle className="w-4 h-4" />
              Reject
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}