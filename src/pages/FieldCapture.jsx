import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import { CheckCircle2, MapPin, Loader2 } from "lucide-react";
import { base44 } from "@/api/base44Client";
import { useQueryClient } from "@tanstack/react-query";
import GPSCapture from "@/components/capture/GPSCapture";
import PhotoUpload from "@/components/capture/PhotoUpload";
import { toast } from "sonner";

const INITIAL = {
  owner_name: "",
  phone: "",
  latitude: null,
  longitude: null,
  description: "",
  photos: [],
};

export default function FieldCapture() {
  const [form, setForm] = useState(INITIAL);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const queryClient = useQueryClient();

  const set = (field, value) => setForm((f) => ({ ...f, [field]: value }));

  const isValid =
    form.owner_name.trim() &&
    form.phone.trim() &&
    form.latitude !== null &&
    form.longitude !== null &&
    form.photos.length > 0;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isValid) return;

    setSubmitting(true);
    await base44.entities.Parcel.create({
      ...form,
      status: "pending",
      captured_at: new Date().toISOString(),
    });
    queryClient.invalidateQueries({ queryKey: ["parcels"] });
    setSubmitting(false);
    setSuccess(true);
    setTimeout(() => {
      setSuccess(false);
      setForm(INITIAL);
    }, 2000);
    toast.success("Parcel saved successfully!");
  };

  if (success) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[80vh] p-6 text-center">
        <div className="w-20 h-20 rounded-full bg-primary/10 flex items-center justify-center mb-4">
          <CheckCircle2 className="w-10 h-10 text-primary" />
        </div>
        <h2 className="text-xl font-bold text-foreground mb-1">Parcel Saved!</h2>
        <p className="text-muted-foreground">Data captured successfully.</p>
      </div>
    );
  }

  return (
    <div className="p-4 pt-6">
      <div className="flex items-center gap-2 mb-6">
        <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
          <MapPin className="w-5 h-5 text-primary-foreground" />
        </div>
        <div>
          <h1 className="text-lg font-bold text-foreground leading-tight">Land Capture</h1>
          <p className="text-xs text-muted-foreground">Ehime Mbano Field Survey</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <Card>
          <CardContent className="p-4 space-y-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">
                Owner Name <span className="text-destructive">*</span>
              </label>
              <Input
                placeholder="Enter full name"
                value={form.owner_name}
                onChange={(e) => set("owner_name", e.target.value)}
                className="h-12 text-base"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">
                Phone Number <span className="text-destructive">*</span>
              </label>
              <Input
                placeholder="+234..."
                type="tel"
                value={form.phone}
                onChange={(e) => set("phone", e.target.value)}
                className="h-12 text-base"
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4 space-y-4">
            <GPSCapture
              latitude={form.latitude}
              longitude={form.longitude}
              onCapture={(lat, lng) => {
                set("latitude", lat);
                set("longitude", lng);
              }}
            />
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4 space-y-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Land Description</label>
              <Textarea
                placeholder="Describe the land parcel..."
                value={form.description}
                onChange={(e) => set("description", e.target.value)}
                className="min-h-[80px] text-base"
              />
            </div>

            <PhotoUpload
              photos={form.photos}
              onPhotosChange={(p) => set("photos", p)}
            />
          </CardContent>
        </Card>

        <Button
          type="submit"
          className="w-full h-14 text-lg font-semibold"
          disabled={!isValid || submitting}
        >
          {submitting ? (
            <>
              <Loader2 className="w-5 h-5 mr-2 animate-spin" />
              Saving...
            </>
          ) : (
            "Save Parcel"
          )}
        </Button>
      </form>
    </div>
  );
}