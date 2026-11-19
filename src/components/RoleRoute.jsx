import { Link } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { homePathFor } from "../utils/roles";

/** Frontend-only guard for UX. The backend enforces the real permission on every API call. */
export default function RoleRoute({ allow, children }) {
  const { user } = useAuth();
  if (user && allow(user)) return children;
  return (
    <div className="max-w-md mx-auto mt-16 card p-8 text-center">
      <h1 className="text-lg font-semibold text-slate-900">Access denied</h1>
      <p className="mt-2 text-sm text-slate-500">Your account does not have permission to view this area.</p>
      <Link to={user ? homePathFor(user) : "/login"} className="btn-primary mt-5">Go to my dashboard</Link>
    </div>
  );
}
