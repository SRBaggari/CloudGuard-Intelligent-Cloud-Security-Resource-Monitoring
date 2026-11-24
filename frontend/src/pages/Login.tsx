import { LogIn } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { Banner, Button, Field, Input } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import AuthShell from "./AuthShell";

export default function LoginPage() {
  const { login, user, ready } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ username?: string; password?: string; form?: string }>({});
  const [loading, setLoading] = useState(false);

  if (ready && user) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const errs: typeof errors = {};
    if (!username.trim()) errs.username = "Enter your username or email";
    if (!password) errs.password = "Enter your password";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setLoading(true);
    try {
      await login(username.trim(), password);
      const from = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(from, { replace: true });
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : "Sign-in failed" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell title="Sign in" subtitle="Access the CloudGuard security console.">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {errors.form && <Banner tone="critical" title="Unable to sign in">{errors.form}</Banner>}
        <Field label="Username or email" htmlFor="username" error={errors.username}>
          <Input id="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password}>
          <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Button type="submit" variant="primary" className="w-full" loading={loading} icon={<LogIn className="size-4" />}>
          Sign in
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        No account yet?{" "}
        <Link to="/register" className="font-medium text-accent hover:underline">Create one</Link>
      </p>
    </AuthShell>
  );
}
