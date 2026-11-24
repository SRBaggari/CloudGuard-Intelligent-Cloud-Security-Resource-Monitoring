import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { EmptyState, Spinner } from "@/components/ui";
import { Lock } from "lucide-react";

export function ProtectedRoute() {
  const { user, ready } = useAuth();
  const location = useLocation();
  if (!ready) return <Spinner label="Checking session…" />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

export function AdminRoute() {
  const { isAdmin } = useAuth();
  if (!isAdmin)
    return (
      <EmptyState
        icon={<Lock className="size-5" />}
        title="Administrator access required"
        message="Your account does not have permission to view this page. Contact a CloudGuard administrator."
      />
    );
  return <Outlet />;
}
