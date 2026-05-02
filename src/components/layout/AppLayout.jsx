import { Outlet } from "react-router-dom";
import AppNav from "./AppNav";

export default function AppLayout() {
  return (
    <div className="min-h-screen bg-background">
      <main className="pb-20 max-w-2xl mx-auto">
        <Outlet />
      </main>
      <AppNav />
    </div>
  );
}