import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import DashboardPage from "@/components/dashboard/DashboardPage";

export default function Page() {
  return (
    <ProtectedRoute>
      <DashboardPage />
    </ProtectedRoute>
  );
}
