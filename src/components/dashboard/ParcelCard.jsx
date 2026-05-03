import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { MapPin, Phone, Calendar, AlertTriangle, CheckCircle2 } from "lucide-react";
import { format } from "date-fns";

const statusColors = {
  pending: "bg-accent/15 text-accent border-accent/30",
  verified: "bg-primary/15 text-primary border-primary/30",
  rejected: "bg-destructive/15 text-destructive border-destructive/30",
  under_review: "bg-chart-5/15 text-chart-5 border-chart-5/30",
};

export default function ParcelCard({ parcel, onClick, selectable, selected, onSelect }) {
  const handleClick = () => {
    if (selectable) {
      onSelect?.(parcel.id);
    } else {
      onClick?.(parcel);
    }
  };

  return (
    <Card
      className={`cursor-pointer transition-all ${
        selected
          ? "ring-2 ring-primary shadow-md"
          : "hover:shadow-md"
      }`}
      onClick={handleClick}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-start gap-2">
            {selectable && (
              <div className={`mt-0.5 w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 transition-colors ${
                selected ? "bg-primary border-primary" : "border-border"
              }`}>
                {selected && <CheckCircle2 className="w-3.5 h-3.5 text-primary-foreground" />}
              </div>
            )}
            <div>
              <h3 className="font-semibold text-foreground">{parcel.owner_name}</h3>
              <div className="flex items-center gap-1 text-sm text-muted-foreground">
                <Phone className="w-3 h-3" />
                {parcel.phone}
              </div>
            </div>
          </div>
          <Badge variant="outline" className={statusColors[parcel.status] || ""}>
            {parcel.status}
          </Badge>
        </div>

        <div className="flex items-center gap-1 text-xs text-muted-foreground mb-2">
          <MapPin className="w-3 h-3" />
          {parcel.latitude?.toFixed(5)}, {parcel.longitude?.toFixed(5)}
        </div>

        {parcel.flags?.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {parcel.flags.map((flag, i) => (
              <Badge key={i} variant="destructive" className="text-[10px] gap-1">
                <AlertTriangle className="w-2.5 h-2.5" />
                {flag}
              </Badge>
            ))}
          </div>
        )}

        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <Calendar className="w-3 h-3" />
            {parcel.captured_at
              ? format(new Date(parcel.captured_at), "dd MMM yyyy, HH:mm")
              : format(new Date(parcel.created_date), "dd MMM yyyy, HH:mm")}
          </span>
          {parcel.photos?.length > 0 && (
            <span>{parcel.photos.length} photo(s)</span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}