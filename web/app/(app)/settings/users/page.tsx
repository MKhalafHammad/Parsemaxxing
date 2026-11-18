"use client";

import { Circle, CircleCheck, CircleX, Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Field, FormError, formValues, PasswordField } from "@/components/auth/fields";
import { AdminOnly, useSession } from "@/components/auth/session";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Confirm } from "@/components/ui/confirm";
import { Dialog } from "@/components/ui/dialog";
import { Label } from "@/components/ui/input";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, postJson, type User } from "@/lib/api";
import { when } from "@/lib/utils";

type Action = { kind: "role" | "disable" | "enable" | "signout"; user: User };
const SELECT = "h-9 rounded-md border border-line-strong bg-surface-solid px-2 text-sm";
const roleWord = (r: string) => (r === "admin" ? "Admin" : "Viewer");

export default function UsersPage() {
  const { me, isAdmin } = useSession();
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState<string | Error>("");
  const [role, setRole] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | Error>("");
  const [action, setAction] = useState<Action | null>(null);
  const [message, setMessage] = useState("");

  const load = useCallback(() => {
    api<User[]>("/auth/users").then(setUsers, setError);
  }, []);
  useEffect(() => {
    if (isAdmin) load(); // the engine lists users to admins only
  }, [isAdmin, load]);

  async function add(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const v = formValues(e);
    setAddError("");
    try {
      const u = await postJson<User>("/auth/users", { username: v("username"), display_name: v("display_name"), role: v("role"), password: v("password") });
      setAdding(false);
      setMessage(`Added ${u.username}. Give them the temporary password; they set up MFA at first sign-in if their role needs it.`);
      load();
    } catch (err) {
      setAddError(err as Error);
    }
  }

  const act = (kind: Action["kind"], user: User) => setAction({ kind, user });
  const shown = (users ?? []).filter((u) => !role || u.role === role);
  const name = action ? action.user.display_name || action.user.username : "";

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Users</h1>
          <p className="text-sm text-muted">Local accounts and their roles. Changing a role or disabling a user signs them out everywhere.</p>
        </div>
        <AdminOnly>
          <Button onClick={() => (setAddError(""), setAdding(true))}>
            <Plus aria-hidden className="h-4 w-4" /> Add user
          </Button>
        </AdminOnly>
      </div>
      <p role="status" aria-live="polite" className="text-sm text-good empty:hidden">
        {message}
      </p>
      <FormError error={error} />

      <section aria-labelledby="users-title" className="glass overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
          <h2 id="users-title" className="text-base font-semibold">
            All users
          </h2>
          {isAdmin && (
            <>
              <Label htmlFor="role-filter" className="ml-auto text-muted">
                Role
              </Label>
              <select id="role-filter" value={role} onChange={(e) => setRole(e.target.value)} className={SELECT}>
                <option value="">All</option>
                <option value="admin">Admin</option>
                <option value="viewer">Viewer</option>
              </select>
            </>
          )}
        </div>
        {!isAdmin ? (
          <p className="p-4 text-sm text-muted">Only admins can see the user list. Ask an admin to add or change a user.</p>
        ) : users === null ? (
          <p aria-busy="true" className="p-4 text-sm text-muted">
            Loading…
          </p>
        ) : shown.length === 0 ? (
          <p className="p-4 text-sm text-muted">
            No users match this filter.{" "}
            <button type="button" className="underline underline-offset-2" onClick={() => setRole("")}>
              Clear filters
            </button>
          </p>
        ) : (
          <Table aria-label="Users">
            <THead>
              <Tr>
                <Th scope="col" className="pl-4">Name</Th>
                <Th scope="col">User name</Th>
                <Th scope="col">Source</Th>
                <Th scope="col">Role</Th>
                <Th scope="col">MFA</Th>
                <Th scope="col">Last sign-in</Th>
                <Th scope="col">Status</Th>
                <Th scope="col">
                  <span className="sr-only">Actions</span>
                </Th>
              </Tr>
            </THead>
            <TBody>
              {shown.map((u) => (
                <Tr key={u.id}>
                  <Td className="pl-4">{u.display_name || u.username}</Td>
                  <Td className="font-mono">{u.username}</Td>
                  <Td>{u.source === "local" ? "Local" : u.source}</Td>
                  <Td>{roleWord(u.role)}</Td>
                  <Td>
                    {u.mfa ? (
                      <span className="inline-flex items-center gap-1">
                        <CircleCheck aria-hidden className="h-3.5 w-3.5 text-good" /> Enrolled
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-muted">
                        <Circle aria-hidden className="h-3.5 w-3.5" /> Not enrolled
                      </span>
                    )}
                  </Td>
                  <Td className="whitespace-nowrap">{when(u.last_login_at)}</Td>
                  <Td>
                    {u.disabled ? (
                      <Badge variant="bad">
                        <CircleX aria-hidden className="h-3.5 w-3.5" /> Disabled
                      </Badge>
                    ) : (
                      <Badge variant="good">
                        <CircleCheck aria-hidden className="h-3.5 w-3.5" /> Active
                      </Badge>
                    )}
                  </Td>
                  <Td>
                    <span className="flex flex-wrap gap-2">
                      <Button size="sm" variant="outline" onClick={() => act("role", u)}>
                        Change role… <span className="sr-only">{u.username}</span>
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => act("signout", u)}>
                        Sign out everywhere… <span className="sr-only">{u.username}</span>
                      </Button>
                      {u.disabled ? (
                        <Button size="sm" variant="outline" onClick={() => act("enable", u)}>
                          Enable user… <span className="sr-only">{u.username}</span>
                        </Button>
                      ) : (
                        <Button size="sm" variant="destructive" disabled={u.id === me?.user.id} onClick={() => act("disable", u)}>
                          Disable user… <span className="sr-only">{u.username}</span>
                        </Button>
                      )}
                    </span>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </section>

      <Dialog open={adding} onClose={() => setAdding(false)} title="Add user">
        <form onSubmit={add} className="grid gap-4">
          <Field id="display_name" label="Name" maxLength={128} autoComplete="off" data-autofocus />
          <Field id="username" label="User name" hint="1 to 64 of a-z, 0-9, '.', '_' and '-'." required maxLength={64} autoComplete="off" autoCapitalize="none" spellCheck={false} />
          <div className="grid gap-1">
            <Label htmlFor="new-role">Role</Label>
            <select id="new-role" name="role" defaultValue="viewer" className={SELECT}>
              <option value="viewer">Viewer</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <PasswordField id="password" label="Temporary password" autoComplete="new-password" hint="12 to 128 characters. Share it with them privately." />
          <FormError error={addError} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setAdding(false)}>
              Cancel
            </Button>
            <Button type="submit">Add user</Button>
          </div>
        </form>
      </Dialog>

      <Confirm
        open={action !== null}
        onClose={() => setAction(null)}
        title={
          action?.kind === "role" ? `Change the role of ${name}?` : action?.kind === "disable" ? `Disable ${name}?` : action?.kind === "enable" ? `Enable ${name}?` : `Sign ${name} out everywhere?`
        }
        confirm={action?.kind === "role" ? "Change role" : action?.kind === "disable" ? "Disable user" : action?.kind === "enable" ? "Enable user" : "Sign out everywhere"}
        destructive={action?.kind === "disable"}
        onConfirm={async (f) => {
          const a = action!;
          const path = { role: "role", disable: "disable", enable: "enable", signout: "sessions/revoke" }[a.kind];
          await postJson(`/auth/users/${a.user.id}/${path}`, a.kind === "role" ? { role: f.get("role") } : {});
          load();
        }}
      >
        {action?.kind === "role" && (
          <div className="grid gap-1">
            <Label htmlFor="change-role">Role</Label>
            <select id="change-role" name="role" defaultValue={action.user.role} className={SELECT}>
              <option value="viewer">Viewer</option>
              <option value="admin">Admin</option>
            </select>
          </div>
        )}
        <p className="text-sm">
          {action?.kind === "enable" ? "They can sign in again." : action?.kind === "disable" ? "Signs them out everywhere. Their approvals and history stay." : "Signs them out everywhere."}
        </p>
      </Confirm>
    </div>
  );
}
