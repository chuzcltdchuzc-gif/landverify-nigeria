import { Card, CardContent } from "@/components/ui/card";
import { Banknote } from "lucide-react";

const FULL_PLOT_RATE = 150000; // NGN
const HALF_PLOT_RATE = 80000;

export default function RevenueEstimate({ parcels }) {
  const verified = parcels.filter((p) => p.status === "verified");
  const fullPlots = verified.filter((p) => p.plot_type === "full").length;
  const halfPlots = verified.filter((p) => p.plot_type === "half").length;
  const unspecified = verified.filter((p) => !p.plot_type).length;

  const total =
    fullPlots * FULL_PLOT_RATE +
    halfPlots * HALF_PLOT_RATE +
    unspecified * FULL_PLOT_RATE;

  const fmt = (n) =>
    new Intl.NumberFormat("en-NG", { style: "currency", currency: "NGN", maximumFractionDigits: 0 }).format(n);

  return (
    <Card className="border-primary/20 bg-primary/5 mb-6">
      <CardContent className="p-4">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-9 h-9 rounded-lg bg-primary flex items-center justify-center">
            <Banknote className="w-4 h-4 text-primary-foreground" />
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Revenue Estimate</p>
            <p className="text-xl font-bold text-primary">{fmt(total)}</p>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center text-xs text-muted-foreground">
          <div className="bg-card rounded-md p-2">
            <p className="font-bold text-foreground text-base">{fullPlots}</p>
            <p>Full plots</p>
          </div>
          <div className="bg-card rounded-md p-2">
            <p className="font-bold text-foreground text-base">{halfPlots}</p>
            <p>Half plots</p>
          </div>
          <div className="bg-card rounded-md p-2">
            <p className="font-bold text-foreground text-base">{verified.length}</p>
            <p>Verified total</p>
          </div>
        </div>
        <p className="text-[10px] text-muted-foreground mt-2 text-center">
          Based on ₦150,000/full plot · ₦80,000/half plot. Estimate only.
        </p>
      </CardContent>
    </Card>
  );
}