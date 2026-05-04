import { ShieldX } from "lucide-react";

export default function AccessDenied() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[70vh] p-8 text-center">
      <div className="w-16 h-16 rounded-full bg-destructive/10 flex items-center justify-center mb-4">
        <ShieldX className="w-8 h-8 text-destructive" />
      </div>
      <h2 className="text-lg font-bold text-foreground mb-1">Access Restricted</h2>
      <p className="text-sm text-muted-foreground max-w-xs">
        Your role does not have permission to view this page. Contact your administrator.
      </p>
    </div>
  );
}