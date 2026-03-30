/**
 * UserManagementPage — Admin UI for managing users, groups, and permissions.
 *
 * Tabs: Users | Groups | LDAP/SSO
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

interface User {
  id: string;
  username: string;
  email: string | null;
  role: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  auth_backend: string;
  groups: string[];
  created_at: string;
}

interface Group {
  id: string;
  name: string;
  description: string;
  member_count: number;
}

interface ObjectPermission {
  id: string;
  name: string;
  enabled: boolean;
  can_read: boolean;
  can_create: boolean;
  can_update: boolean;
  can_delete: boolean;
  object_types: string[];
  can_execute_jobs: boolean;
  allowed_jobs: string[];
}

type Tab = "users" | "groups" | "auth";

const ROLES = ["viewer", "editor", "operator", "admin", "superadmin"];

export function UserManagementPage() {
  const [activeTab, setActiveTab] = useState<Tab>("users");

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">User & Group Management</h1>
        <p className="mt-1 text-sm text-gray-500">Manage users, groups, permissions, and authentication backends</p>
      </div>

      {/* Tabs */}
      <div className="mb-6 border-b border-gray-200 dark:border-gray-700">
        <div className="flex gap-4">
          {([["users", "Users"], ["groups", "Groups"], ["auth", "LDAP / SSO"]] as const).map(([id, label]) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`border-b-2 pb-2 text-sm font-medium ${
                activeTab === id
                  ? "border-brand-500 text-brand-600"
                  : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {activeTab === "users" && <UsersTab />}
      {activeTab === "groups" && <GroupsTab />}
      {activeTab === "auth" && <AuthConfigTab />}
    </div>
  );
}

// ─── Users Tab ──────────────────────────────────────────────────────────────

function UsersTab() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [resetUserId, setResetUserId] = useState<string | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => api.get("/auth/users"),
  });
  const users: User[] = data?.data?.data || [];

  const createMutation = useMutation({
    mutationFn: (user: Record<string, unknown>) => api.post("/auth/users", user),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin-users"] }); setShowCreate(false); },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      api.patch(`/auth/users/${id}`, { is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const resetMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) =>
      api.post(`/auth/users/${id}/reset-password`, { new_password: password }),
    onSuccess: () => { setResetUserId(null); setNewPassword(""); },
  });

  return (
    <div>
      <div className="mb-4 flex justify-end">
        <button onClick={() => setShowCreate(!showCreate)} className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">
          {showCreate ? "Cancel" : "Create User"}
        </button>
      </div>

      {showCreate && (
        <CreateUserForm onSubmit={(u) => createMutation.mutate(u)} isPending={createMutation.isPending} error={createMutation.error} />
      )}

      {/* Password reset dialog */}
      {resetUserId && (
        <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
          <h3 className="mb-2 text-sm font-semibold">Reset Password</h3>
          <div className="flex gap-2">
            <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)}
              placeholder="New password (min 8 chars)" className="flex-1 rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            <button onClick={() => resetMutation.mutate({ id: resetUserId, password: newPassword })}
              disabled={newPassword.length < 8} className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white hover:bg-amber-700 disabled:opacity-50">
              Reset
            </button>
            <button onClick={() => setResetUserId(null)} className="rounded border border-gray-300 px-3 py-1.5 text-sm">Cancel</button>
          </div>
        </div>
      )}

      {isLoading ? <div className="text-gray-500">Loading...</div> : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                {["Username", "Email", "Role", "Groups", "Backend", "Status", "Actions"].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900 dark:text-white">
                    {u.username}
                    {u.first_name && <span className="ml-1 text-xs text-gray-500">({u.first_name} {u.last_name})</span>}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">{u.email || "—"}</td>
                  <td className="px-4 py-3"><RoleBadge role={u.role} /></td>
                  <td className="px-4 py-3 text-sm text-gray-500">{u.groups?.join(", ") || "—"}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{u.auth_backend || "local"}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${u.is_active ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"}`}>
                      {u.is_active ? "Active" : "Disabled"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <div className="flex gap-1">
                      <button onClick={() => setResetUserId(u.id)} className="rounded border px-2 py-1 text-xs hover:bg-gray-100 dark:hover:bg-gray-700">Reset PW</button>
                      <button onClick={() => toggleMutation.mutate({ id: u.id, is_active: !u.is_active })}
                        className={`rounded border px-2 py-1 text-xs ${u.is_active ? "text-red-600 hover:bg-red-50" : "text-green-600 hover:bg-green-50"}`}>
                        {u.is_active ? "Disable" : "Enable"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CreateUserForm({ onSubmit, isPending, error }: { onSubmit: (u: Record<string, unknown>) => void; isPending: boolean; error: unknown }) {
  const [form, setForm] = useState({ username: "", email: "", password: "", role: "viewer", first_name: "", last_name: "" });

  return (
    <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <h3 className="mb-3 text-sm font-semibold">Create User</h3>
      <div className="grid grid-cols-3 gap-3">
        {[
          { key: "username", label: "Username", required: true },
          { key: "email", label: "Email" },
          { key: "password", label: "Password", type: "password", required: true },
          { key: "first_name", label: "First Name" },
          { key: "last_name", label: "Last Name" },
        ].map((f) => (
          <div key={f.key}>
            <label className="mb-1 block text-xs font-medium text-gray-500">{f.label}</label>
            <input type={f.type || "text"} value={(form as Record<string, string>)[f.key]}
              onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
              className="w-full rounded border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
          </div>
        ))}
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-500">Role</label>
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}
            className="w-full rounded border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
      </div>
      {error && <div className="mt-2 text-sm text-red-500">{String(error)}</div>}
      <div className="mt-3 flex justify-end">
        <button onClick={() => onSubmit(form)} disabled={isPending || !form.username || !form.password}
          className="rounded bg-brand-600 px-4 py-1.5 text-sm text-white hover:bg-brand-700 disabled:opacity-50">
          {isPending ? "Creating..." : "Create User"}
        </button>
      </div>
    </div>
  );
}

// ─── Groups Tab ─────────────────────────────────────────────────────────────

function GroupsTab() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [newGroupName, setNewGroupName] = useState("");
  const [newGroupDesc, setNewGroupDesc] = useState("");

  const { data } = useQuery({ queryKey: ["admin-groups"], queryFn: () => api.get("/auth/groups") });
  const groups: Group[] = data?.data?.data || [];

  const { data: groupDetail } = useQuery({
    queryKey: ["admin-group", selectedGroup],
    queryFn: () => api.get(`/auth/groups/${selectedGroup}`),
    enabled: !!selectedGroup,
  });
  const detail = groupDetail?.data?.data;

  const createMutation = useMutation({
    mutationFn: () => api.post("/auth/groups", { name: newGroupName, description: newGroupDesc }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin-groups"] }); setShowCreate(false); setNewGroupName(""); setNewGroupDesc(""); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/auth/groups/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin-groups"] }); setSelectedGroup(null); },
  });

  return (
    <div className="grid grid-cols-3 gap-6">
      {/* Group list */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Groups</h3>
          <button onClick={() => setShowCreate(!showCreate)} className="rounded bg-brand-600 px-2 py-1 text-xs text-white hover:bg-brand-700">+ New</button>
        </div>

        {showCreate && (
          <div className="mb-3 rounded border border-gray-200 p-3 dark:border-gray-700">
            <input type="text" value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} placeholder="Group name"
              className="mb-2 w-full rounded border border-gray-300 px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            <input type="text" value={newGroupDesc} onChange={(e) => setNewGroupDesc(e.target.value)} placeholder="Description"
              className="mb-2 w-full rounded border border-gray-300 px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            <button onClick={() => createMutation.mutate()} disabled={!newGroupName}
              className="rounded bg-brand-600 px-3 py-1 text-xs text-white hover:bg-brand-700 disabled:opacity-50">Create</button>
          </div>
        )}

        <div className="space-y-1">
          {groups.map((g) => (
            <button key={g.id} onClick={() => setSelectedGroup(g.id)}
              className={`flex w-full items-center justify-between rounded px-3 py-2 text-left text-sm ${selectedGroup === g.id ? "bg-brand-50 text-brand-700 dark:bg-brand-900/20" : "hover:bg-gray-50 dark:hover:bg-gray-700"}`}>
              <div>
                <div className="font-medium">{g.name}</div>
                {g.description && <div className="text-xs text-gray-500">{g.description}</div>}
              </div>
              <span className="text-xs text-gray-400">{g.member_count} members</span>
            </button>
          ))}
          {groups.length === 0 && <div className="px-3 py-4 text-center text-sm text-gray-500">No groups created</div>}
        </div>
      </div>

      {/* Group detail */}
      <div className="col-span-2">
        {detail ? (
          <div>
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{detail.name}</h3>
                {detail.description && <p className="text-sm text-gray-500">{detail.description}</p>}
              </div>
              <button onClick={() => { if (confirm(`Delete group "${detail.name}"?`)) deleteMutation.mutate(detail.id); }}
                className="rounded border border-red-300 px-3 py-1 text-xs text-red-600 hover:bg-red-50">Delete Group</button>
            </div>

            {/* Members */}
            <div className="mb-4">
              <h4 className="mb-2 text-sm font-semibold text-gray-700 dark:text-gray-300">Members ({detail.members?.length || 0})</h4>
              <div className="rounded border border-gray-200 dark:border-gray-700">
                {detail.members?.map((m: { id: string; username: string; role: string; is_active: boolean }) => (
                  <div key={m.id} className="flex items-center justify-between border-b border-gray-100 px-3 py-2 last:border-0 dark:border-gray-700">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{m.username}</span>
                      <RoleBadge role={m.role} />
                    </div>
                    <RemoveMemberButton groupId={detail.id} userId={m.id} />
                  </div>
                ))}
                {(!detail.members || detail.members.length === 0) && (
                  <div className="px-3 py-4 text-center text-sm text-gray-500">No members</div>
                )}
              </div>
              <AddMemberForm groupId={detail.id} />
            </div>

            {/* Permissions */}
            <div>
              <h4 className="mb-2 text-sm font-semibold text-gray-700 dark:text-gray-300">Object Permissions ({detail.permissions?.length || 0})</h4>
              <PermissionsList groupId={detail.id} permissions={detail.permissions || []} />
            </div>
          </div>
        ) : (
          <div className="flex h-64 items-center justify-center text-sm text-gray-500">Select a group to manage</div>
        )}
      </div>
    </div>
  );
}

function AddMemberForm({ groupId }: { groupId: string }) {
  const queryClient = useQueryClient();
  const [userId, setUserId] = useState("");
  const { data } = useQuery({ queryKey: ["admin-users"], queryFn: () => api.get("/auth/users") });
  const users: User[] = data?.data?.data || [];

  const mutation = useMutation({
    mutationFn: () => api.post(`/auth/groups/${groupId}/members`, { user_id: userId }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin-group", groupId] }); queryClient.invalidateQueries({ queryKey: ["admin-groups"] }); setUserId(""); },
  });

  return (
    <div className="mt-2 flex gap-2">
      <select value={userId} onChange={(e) => setUserId(e.target.value)}
        className="flex-1 rounded border border-gray-300 px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
        <option value="">Add user...</option>
        {users.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
      </select>
      <button onClick={() => mutation.mutate()} disabled={!userId}
        className="rounded bg-brand-600 px-3 py-1 text-xs text-white hover:bg-brand-700 disabled:opacity-50">Add</button>
    </div>
  );
}

function RemoveMemberButton({ groupId, userId }: { groupId: string; userId: string }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => api.delete(`/auth/groups/${groupId}/members/${userId}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin-group", groupId] }); queryClient.invalidateQueries({ queryKey: ["admin-groups"] }); },
  });
  return (
    <button onClick={() => mutation.mutate()} className="text-xs text-red-500 hover:text-red-700">Remove</button>
  );
}

function PermissionsList({ groupId, permissions }: { groupId: string; permissions: ObjectPermission[] }) {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", can_read: true, can_create: false, can_update: false, can_delete: false, object_types: "", can_execute_jobs: false, allowed_jobs: "" });

  const createMutation = useMutation({
    mutationFn: () => api.post(`/auth/groups/${groupId}/permissions`, {
      ...form,
      object_types: form.object_types ? form.object_types.split(",").map((s) => s.trim()) : [],
      allowed_jobs: form.allowed_jobs ? form.allowed_jobs.split(",").map((s) => s.trim()) : [],
    }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin-group", groupId] }); setShowCreate(false); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/auth/permissions/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-group", groupId] }),
  });

  return (
    <div>
      <div className="mb-2 flex justify-end">
        <button onClick={() => setShowCreate(!showCreate)} className="rounded bg-brand-600 px-2 py-1 text-xs text-white hover:bg-brand-700">
          + Add Permission
        </button>
      </div>

      {showCreate && (
        <div className="mb-3 rounded border border-gray-200 p-3 dark:border-gray-700">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs font-medium text-gray-500">Permission Name</label>
              <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full rounded border px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500">Object Types (comma-separated, empty=all)</label>
              <input type="text" value={form.object_types} onChange={(e) => setForm({ ...form, object_types: e.target.value })}
                placeholder="Device, Interface, Prefix" className="w-full rounded border px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </div>
          </div>
          <div className="mt-2 flex flex-wrap gap-4">
            {(["can_read", "can_create", "can_update", "can_delete", "can_execute_jobs"] as const).map((f) => (
              <label key={f} className="flex items-center gap-1 text-xs">
                <input type="checkbox" checked={(form as Record<string, boolean>)[f] as boolean}
                  onChange={(e) => setForm({ ...form, [f]: e.target.checked })} />
                {f.replace("can_", "").replace("_", " ")}
              </label>
            ))}
          </div>
          {form.can_execute_jobs && (
            <div className="mt-2">
              <label className="text-xs font-medium text-gray-500">Allowed Jobs (comma-separated, empty=all)</label>
              <input type="text" value={form.allowed_jobs} onChange={(e) => setForm({ ...form, allowed_jobs: e.target.value })}
                className="w-full rounded border px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </div>
          )}
          <div className="mt-2 flex justify-end">
            <button onClick={() => createMutation.mutate()} disabled={!form.name}
              className="rounded bg-brand-600 px-3 py-1 text-xs text-white hover:bg-brand-700 disabled:opacity-50">Create</button>
          </div>
        </div>
      )}

      <div className="rounded border border-gray-200 dark:border-gray-700">
        {permissions.map((p) => (
          <div key={p.id} className="flex items-center justify-between border-b border-gray-100 px-3 py-2 last:border-0 dark:border-gray-700">
            <div>
              <div className="text-sm font-medium">{p.name}</div>
              <div className="flex gap-2 text-xs text-gray-500">
                {p.can_read && <span className="text-green-600">Read</span>}
                {p.can_create && <span className="text-blue-600">Create</span>}
                {p.can_update && <span className="text-amber-600">Update</span>}
                {p.can_delete && <span className="text-red-600">Delete</span>}
                {p.can_execute_jobs && <span className="text-purple-600">Jobs</span>}
                {p.object_types?.length > 0 && <span>| Types: {p.object_types.join(", ")}</span>}
              </div>
            </div>
            <button onClick={() => deleteMutation.mutate(p.id)} className="text-xs text-red-500 hover:text-red-700">Remove</button>
          </div>
        ))}
        {permissions.length === 0 && <div className="px-3 py-4 text-center text-sm text-gray-500">No permissions configured</div>}
      </div>
    </div>
  );
}

// ─── Auth Config Tab ────────────────────────────────────────────────────────

function AuthConfigTab() {
  const { data: ldapData } = useQuery({ queryKey: ["ldap-config"], queryFn: () => api.get("/auth/config/ldap") });
  const { data: ssoData } = useQuery({ queryKey: ["sso-config"], queryFn: () => api.get("/auth/config/sso") });
  const ldap = ldapData?.data?.data || { enabled: false };
  const sso = ssoData?.data?.data || { enabled: false };

  const ldapMutation = useMutation({ mutationFn: (body: Record<string, unknown>) => api.put("/auth/config/ldap", body) });
  const ssoMutation = useMutation({ mutationFn: (body: Record<string, unknown>) => api.put("/auth/config/sso", body) });

  const [ldapForm, setLdapForm] = useState<Record<string, unknown>>(ldap);
  const [ssoForm, setSsoForm] = useState<Record<string, unknown>>(sso);

  return (
    <div className="space-y-6">
      {/* LDAP */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">LDAP / Active Directory</h3>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={!!ldapForm.enabled} onChange={(e) => setLdapForm({ ...ldapForm, enabled: e.target.checked })} />
            Enabled
          </label>
        </div>
        <div className="grid grid-cols-2 gap-4">
          {[
            { key: "server_uri", label: "Server URI", placeholder: "ldap://dc.example.com:389" },
            { key: "bind_dn", label: "Bind DN", placeholder: "CN=svc-netgraphy,OU=Service Accounts,DC=example,DC=com" },
            { key: "bind_password", label: "Bind Password", type: "password" },
            { key: "user_search_base", label: "User Search Base", placeholder: "OU=Users,DC=example,DC=com" },
            { key: "user_search_filter", label: "User Search Filter", placeholder: "(sAMAccountName={username})" },
            { key: "group_search_base", label: "Group Search Base", placeholder: "OU=Groups,DC=example,DC=com" },
            { key: "require_group", label: "Required Group DN (optional)" },
            { key: "default_role", label: "Default Role" },
          ].map((f) => (
            <div key={f.key}>
              <label className="mb-1 block text-xs font-medium text-gray-500">{f.label}</label>
              <input type={f.type || "text"} value={String(ldapForm[f.key] || "")} placeholder={f.placeholder}
                onChange={(e) => setLdapForm({ ...ldapForm, [f.key]: e.target.value })}
                className="w-full rounded border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-4">
          <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={!!ldapForm.start_tls} onChange={(e) => setLdapForm({ ...ldapForm, start_tls: e.target.checked })} /> StartTLS</label>
          <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={!!ldapForm.auto_create_user} onChange={(e) => setLdapForm({ ...ldapForm, auto_create_user: e.target.checked })} /> Auto-create users</label>
          <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={!!ldapForm.auto_sync_groups} onChange={(e) => setLdapForm({ ...ldapForm, auto_sync_groups: e.target.checked })} /> Sync groups</label>
        </div>
        <div className="mt-4 flex justify-end">
          <button onClick={() => ldapMutation.mutate(ldapForm)} className="rounded bg-brand-600 px-4 py-1.5 text-sm text-white hover:bg-brand-700">
            {ldapMutation.isPending ? "Saving..." : "Save LDAP Config"}
          </button>
        </div>
      </div>

      {/* SSO */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">Single Sign-On (SAML / OIDC)</h3>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={!!ssoForm.enabled} onChange={(e) => setSsoForm({ ...ssoForm, enabled: e.target.checked })} />
            Enabled
          </label>
        </div>
        <div className="mb-3">
          <label className="mb-1 block text-xs font-medium text-gray-500">Provider Type</label>
          <select value={String(ssoForm.provider_type || "none")} onChange={(e) => setSsoForm({ ...ssoForm, provider_type: e.target.value })}
            className="rounded border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
            <option value="none">None</option>
            <option value="oidc">OIDC (OpenID Connect)</option>
            <option value="saml">SAML 2.0</option>
          </select>
        </div>
        <div className="grid grid-cols-2 gap-4">
          {ssoForm.provider_type === "oidc" && [
            { key: "oidc_discovery_url", label: "Discovery URL", placeholder: "https://idp.example.com/.well-known/openid-configuration" },
            { key: "oidc_client_id", label: "Client ID" },
            { key: "oidc_client_secret", label: "Client Secret", type: "password" },
            { key: "group_claim", label: "Group Claim", placeholder: "groups" },
            { key: "default_role", label: "Default Role" },
          ].map((f) => (
            <div key={f.key}>
              <label className="mb-1 block text-xs font-medium text-gray-500">{f.label}</label>
              <input type={f.type || "text"} value={String(ssoForm[f.key] || "")} placeholder={f.placeholder}
                onChange={(e) => setSsoForm({ ...ssoForm, [f.key]: e.target.value })}
                className="w-full rounded border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </div>
          ))}
          {ssoForm.provider_type === "saml" && [
            { key: "saml_idp_metadata_url", label: "IdP Metadata URL" },
            { key: "saml_idp_sso_url", label: "IdP SSO URL" },
            { key: "saml_sp_entity_id", label: "SP Entity ID" },
            { key: "group_claim", label: "Group Attribute", placeholder: "groups" },
            { key: "default_role", label: "Default Role" },
          ].map((f) => (
            <div key={f.key}>
              <label className="mb-1 block text-xs font-medium text-gray-500">{f.label}</label>
              <input type="text" value={String(ssoForm[f.key] || "")} placeholder={f.placeholder}
                onChange={(e) => setSsoForm({ ...ssoForm, [f.key]: e.target.value })}
                className="w-full rounded border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </div>
          ))}
        </div>
        <div className="mt-4 flex justify-end">
          <button onClick={() => ssoMutation.mutate(ssoForm)} className="rounded bg-brand-600 px-4 py-1.5 text-sm text-white hover:bg-brand-700">
            {ssoMutation.isPending ? "Saving..." : "Save SSO Config"}
          </button>
        </div>
      </div>
    </div>
  );
}

function RoleBadge({ role }: { role: string }) {
  const colors: Record<string, string> = {
    viewer: "bg-gray-100 text-gray-700",
    editor: "bg-blue-100 text-blue-700",
    operator: "bg-purple-100 text-purple-700",
    admin: "bg-red-100 text-red-700",
    superadmin: "bg-red-200 text-red-800",
  };
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${colors[role] || colors.viewer}`}>
      {role}
    </span>
  );
}
