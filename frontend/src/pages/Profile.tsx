import { KeyRound, UserCog } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Card, CardHeader, Field, Input, PageHeader, Pagination, Select, Spinner, Table, useToast } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, titleCase } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useTheme, type ThemePreference } from "@/lib/theme";
import type { LoginAttempt, Page } from "@/lib/types";

export default function Profile() {
  const { user, refreshUser } = useAuth();
  const { preference, setPreference } = useTheme();
  const toast = useToast();
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [saving, setSaving] = useState(false);
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const [pwErr, setPwErr] = useState("");
  const [pwSaving, setPwSaving] = useState(false);
  const [page, setPage] = useState(1);
  const history = useApi<Page<LoginAttempt>>("/api/auth/login-history", { query: { page, page_size: 10 } });
  useEffect(() => { setFullName(user?.full_name ?? ""); setEmail(user?.email ?? ""); }, [user]);

  async function saveProfile(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api("/api/auth/me", { method: "PATCH", body: { full_name: fullName, email } });
      await refreshUser();
      toast({ tone: "good", title: "Profile updated" });
    } catch (err) {
      toast({ tone: "critical", title: "Update failed", message: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  }

  async function changePassword(e: FormEvent) {
    e.preventDefault();
    setPwErr("");
    if (pw.next.length < 8 || !/[A-Za-z]/.test(pw.next) || !/\d/.test(pw.next)) return setPwErr("New password needs 8+ characters with letters and numbers");
    if (pw.next !== pw.confirm) return setPwErr("Passwords do not match");
    setPwSaving(true);
    try {
      await api("/api/auth/change-password", { method: "POST", body: { current_password: pw.current, new_password: pw.next } });
      setPw({ current: "", next: "", confirm: "" });
      toast({ tone: "good", title: "Password changed", message: "Other sessions have been signed out." });
    } catch (err) {
      setPwErr(err instanceof ApiError ? err.message : String(err));
    } finally {
      setPwSaving(false);
    }
  }

  if (!user) return <Spinner />;
  return (
    <div className="space-y-6">
      <PageHeader title="Profile & security" description={<>Signed in as <b className="text-ink-2">{user.username}</b> · <Badge tone={user.role_name === "admin" ? "info" : "neutral"}>{titleCase(user.role_name)}</Badge></>} />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Profile" icon={<UserCog className="size-4" />} />
          <form onSubmit={saveProfile} className="space-y-4 p-5">
            <Field label="Full name" htmlFor="p-name"><Input id="p-name" value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={128} /></Field>
            <Field label="Email" htmlFor="p-email"><Input id="p-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
            <Field label="Username" htmlFor="p-user" hint="Usernames cannot be changed"><Input id="p-user" value={user.username} disabled /></Field>
            <Field label="Appearance" htmlFor="p-theme" hint="Saved to your profile and applied on every device you sign in from">
              <Select id="p-theme" value={preference} onChange={async (e) => {
                const v = e.target.value as ThemePreference;
                setPreference(v);
                try {
                  await api("/api/auth/me", { method: "PATCH", body: { theme_preference: v } });
                  await refreshUser();
                  toast({ tone: "good", title: "Appearance saved" });
                } catch (err) {
                  toast({ tone: "critical", title: "Could not save appearance", message: (err as Error).message });
                }
              }}>
                <option value="dark">Dark</option><option value="light">Light</option><option value="system">Match system setting</option>
              </Select>
            </Field>
            <div className="flex justify-end"><Button type="submit" variant="primary" loading={saving}>Save profile</Button></div>
          </form>
        </Card>
        <Card>
          <CardHeader title="Change password" icon={<KeyRound className="size-4" />} />
          <form onSubmit={changePassword} className="space-y-4 p-5">
            <Field label="Current password" htmlFor="pw-cur"><Input id="pw-cur" type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} /></Field>
            <Field label="New password" htmlFor="pw-new"><Input id="pw-new" type="password" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} /></Field>
            <Field label="Confirm new password" htmlFor="pw-conf" error={pwErr}><Input id="pw-conf" type="password" autoComplete="new-password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} /></Field>
            <div className="flex justify-end"><Button type="submit" variant="primary" loading={pwSaving}>Update password</Button></div>
          </form>
        </Card>
      </div>
      <Card>
        <CardHeader title="Login history" subtitle="Recent sign-in attempts for your account" />
        {!history.data ? <Spinner /> : (
          <>
            <Table head={["Time", "Result", "IP address", "Client"]}>
              {history.data.items.map((a) => (
                <tr key={a.id}>
                  <td className="px-4 py-2.5 text-xs text-muted">{formatDateTime(a.created_at)}</td>
                  <td className="px-4 py-2.5"><Badge tone={a.success ? "good" : "critical"} dot>{a.success ? "Success" : titleCase(a.reason)}</Badge></td>
                  <td className="px-4 py-2.5 font-mono text-xs text-ink-2">{a.ip_address}</td>
                  <td className="max-w-md truncate px-4 py-2.5 text-xs text-muted">{a.user_agent}</td>
                </tr>
              ))}
            </Table>
            <Pagination page={history.data.page} pageSize={history.data.page_size} total={history.data.total} onPage={setPage} />
          </>
        )}
      </Card>
    </div>
  );
}
