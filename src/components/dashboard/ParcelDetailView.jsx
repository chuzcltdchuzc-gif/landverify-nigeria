import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  XCircle, MapPin, Phone, Calendar, Image, ShieldCheck,
  Tag, Landmark, Users, UserCheck, FileText
} from "lucide-react";
import { format } from "date-fns";

const statusColors = {
  pending: "bg-accent/15 text-accent border-accent/30",
  verified: "bg-primary/15 text-primary border-primary/30",
  rejected: "bg-destructive/15 text-destructive border-destructive/30",
  under_review: "bg-blue-500/15 text-blue-600 border-blue-300/30",
};

function Section({ icon: Icon, title, children }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
        <Icon className="w-4 h-4 text-primary" />
        {title}
      </div>
      {children}
    </div>
  );
}

export default function ParcelDetailView({ parcel, onClose }) {
  return (
    <div className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-end sm:items-center justify-center">
      <Card className="w-full max-w-lg max-h-[92vh] overflow-y-auto m-2 shadow-xl">
        <CardHeader className="pb-3 sticky top-0 bg-card z-10 border-b border-border">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Parcel Detail</CardTitle>
            <Button variant="ghost" size="sm" onClick={onClose}>
              <XCircle className="w-4 h-4" />
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-5 pt-4">
          {/* Owner Info */}
          <Section icon={UserCheck} title="Owner Information">
            <div className="bg-muted rounded-lg p-3 space-y-1.5">
              <p className="font-semibold text-lg text-foreground">{parcel.owner_name}</p>
              <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <Phone className="w-3.5 h-3.5" /> {parcel.phone}
              </div>
              <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <MapPin className="w-3.5 h-3.5" />
                {parcel.latitude?.toFixed(6)}, {parcel.longitude?.toFixed(6)}
              </div>
              {parcel.captured_at && (
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Calendar className="w-3 h-3" />
                  {format(new Date(parcel.captured_at), "dd MMM yyyy, HH:mm")}
                </div>
              )}
            </div>
          </Section>

          {/* Status & Land ID */}
          <Section icon={ShieldCheck} title="Status & Verification">
            <div className="flex items-center gap-3 flex-wrap">
              <Badge variant="outline" className={statusColors[parcel.status] || ""}>
                {parcel.status}
              </Badge>
              {parcel.confidence_score != null && (
                <span className="text-sm text-muted-foreground">
                  Confidence: <span className="font-bold text-foreground">{parcel.confidence_score}%</span>
                </span>
              )}
            </div>
            {parcel.land_id && (
              <div className="flex items-center gap-2 mt-2 p-2 bg-primary/5 rounded-lg border border-primary/20">
                <Tag className="w-4 h-4 text-primary" />
                <span className="text-sm font-mono font-semibold text-primary">{parcel.land_id}</span>
              </div>
            )}
            {parcel.verification_notes && (
              <p className="text-sm text-muted-foreground bg-muted p-2 rounded-md">
                {parcel.verification_notes}
              </p>
            )}
          </Section>

          {/* Plot Info */}
          <Section icon={Landmark} title="Plot Details">
            <div className="grid grid-cols-2 gap-2">
              {parcel.plot_type && (
                <div className="bg-muted rounded-md p-2">
                  <p className="text-[10px] text-muted-foreground uppercase font-medium">Plot Type</p>
                  <p className="text-sm font-semibold capitalize">{parcel.plot_type}</p>
                </div>
              )}
              {parcel.ownership_type && (
                <div className="bg-muted rounded-md p-2">
                  <p className="text-[10px] text-muted-foreground uppercase font-medium">Ownership</p>
                  <p className="text-sm font-semibold capitalize">{parcel.ownership_type?.replace("_", " ")}</p>
                </div>
              )}
            </div>
          </Section>

          {/* Land History */}
          {(parcel.family_history || parcel.purchased_from) && (
            <Section icon={Users} title="Land History">
              {parcel.family_history && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1 font-medium">Family History</p>
                  <p className="text-sm text-foreground bg-muted p-3 rounded-lg">{parcel.family_history}</p>
                </div>
              )}
              {parcel.purchased_from && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1 font-medium">Purchased From</p>
                  <p className="text-sm text-foreground bg-muted p-3 rounded-lg">{parcel.purchased_from}</p>
                </div>
              )}
            </Section>
          )}

          {/* Description */}
          {parcel.description && (
            <Section icon={FileText} title="Description">
              <p className="text-sm text-muted-foreground bg-muted p-3 rounded-lg">{parcel.description}</p>
            </Section>
          )}

          {/* Photos */}
          {parcel.photos?.length > 0 && (
            <Section icon={Image} title={`Photos (${parcel.photos.length})`}>
              <div className="flex gap-2 overflow-x-auto pb-2">
                {parcel.photos.map((url, i) => (
                  <img
                    key={i}
                    src={url}
                    alt={`Photo ${i + 1}`}
                    className="w-28 h-28 rounded-lg object-cover border border-border flex-shrink-0"
                  />
                ))}
              </div>
            </Section>
          )}
        </CardContent>
      </Card>
    </div>
  );
}