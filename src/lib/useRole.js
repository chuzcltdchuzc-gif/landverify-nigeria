import { useAuth } from "@/lib/AuthContext";

// Roles: field_agent | surveyor | government | admin
export function useRole() {
  const { user } = useAuth();
  const role = user?.role || "field_agent";

  return {
    role,
    isAdmin: role === "admin",
    isSurveyor: role === "surveyor" || role === "admin",
    isGovernment: role === "government" || role === "admin",
    isFieldAgent: role === "field_agent" || role === "admin",
    canCapture: ["field_agent", "admin"].includes(role),
    canVerify: ["surveyor", "admin"].includes(role),
    canViewDashboard: ["surveyor", "government", "admin"].includes(role),
    canViewGuide: true,
  };
}