import { UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Banner, Button, Field, Input, useToast } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { User } from "@/lib/types";
import AuthShell from "./AuthShell";

type Form = { email: string; username: string; full_name: string; password: string; confirm: string };

export function validateRegistration(f: Form): Partial<Record<keyof Form, string>> {
  const e: Partial<Record<keyof Form, string>> = {};
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(f.email)) e.email = "Enter a valid email address";
  if (!/^[A-Za-z0-9_.-]{3,64}$/.test(f.username)) e.username = "3–64 characters: letters, numbers, . _ -";
  if (f.password.length < 8) e.password = "At least 8 characters";
  else if (!/[A-Za-z]/.test(f.password) || !/\d/.test(f.password)) e.password = "Use both letters and numbers";
  if (f.confirm !== f.password) e.confirm = "Passwords do not match";
  return e;
}

export default function RegisterPage() {
  const [form, setForm] = useState<Form>({ email: "", username: "", full_name: "", password: "", confirm: "" });
  const [errors, setErrors] = useState<Partial<Record<keyof Form | "form", string>>>({});
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const errs = validateRegistration(form);
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setLoading(true);
    try {
      const user = await api<User>("/api/auth/register", {
        method: "POST", auth: false,
        body: { email: form.email, username: form.username, full_name: form.full_name, password: form.password },
      });
      await login(form.username, form.password);
      toast({ tone: "good", title: "Account created", message: user.role_name === "admin" ? "You are the first user and have been made administrator." : undefined });
      navigate("/");
    } catch (err) {
      if (err instanceof ApiError && err.fieldErrors.length) {
        setErrors(Object.fromEntries(err.fieldErrors.map((f) => [f.field, f.message.replace(/^Value error, /, "")])));
      } else setErrors({ form: err instanceof ApiError ? err.message : "Registration failed" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell title="Create your account" subtitle="The first account registered becomes the administrator.">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {errors.form && <Banner tone="critical" title="Registration failed">{errors.form}</Banner>}
        <Field label="Email" htmlFor="email" error={errors.email}>
          <Input id="email" type="email" autoComplete="email" value={form.email} onChange={set("email")} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Username" htmlFor="reg-username" error={errors.username}>
            <Input id="reg-username" autoComplete="username" value={form.username} onChange={set("username")} />
          </Field>
          <Field label="Full name (optional)" htmlFor="full_name">
            <Input id="full_name" autoComplete="name" value={form.full_name} onChange={set("full_name")} />
          </Field>
        </div>
        <Field label="Password" htmlFor="reg-password" error={errors.password} hint="At least 8 characters with letters and numbers">
          <Input id="reg-password" type="password" autoComplete="new-password" value={form.password} onChange={set("password")} />
        </Field>
        <Field label="Confirm password" htmlFor="confirm" error={errors.confirm}>
          <Input id="confirm" type="password" autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />
        </Field>
        <Button type="submit" variant="primary" className="w-full" loading={loading} icon={<UserPlus className="size-4" />}>
          Create account
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        Already registered? <Link to="/login" className="font-medium text-accent hover:underline">Sign in</Link>
      </p>
    </AuthShell>
  );
}
