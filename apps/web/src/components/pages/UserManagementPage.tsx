/**
 * UserManagementPage — Admin UI for managing users, groups, and permissions.
 *
 * Tabs: Users | Groups | Permissions | LDAP/SSO
 *
 * Key UX:
 * - Users tab: inline group assignment per user, role changes, password reset
 * - Groups tab: create groups, add/remove members
 * - Permissions tab: per-model CRUD matrix with checkbox grid for each group
 * - LDAP/SSO tab: configure external auth backends
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useSchemaStore } from "@/stores/schemaStore";

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

interface ObjPerm {
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

type Tab = "users" | "groups" | "permissions" | "auth";

const ROLES = ["viewer", "editor", "operator", "admin", "superadmin"];

export function UserManagementPage() {
  const [activeTab, setActiveTab] = useState<Tab>("users");

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">User & Group Management</h1>
        <p className="mt-1 text-sm text-gray-500">Manage users, groups, per-model permissions, and authentication backends</p>
      </div>

      <div className="mb-6 border-b border-gray-200 dark:border-gray-700">
        <div className="flex gap-4">
          {([
            ["users", "Users"],
            ["groups", "Groups"],
            ["permissions", "Permissions"],
            ["auth", "LDAP / SSO"],
          ] as const).map(([id, label]) => (
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
      {activeTab === "permissions" && <PermissionsTab />}
      {activeTab === "auth" && <AuthConfigTab />}
    </div>
  );
}

// ─── Users Tab ──────────────────────────────────────────────────────────────

function UsersTab() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [editingUser, setEditingUser] = useState<string | null>(null);
  const [resetUserId, setResetUserId] = useState<string | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const { data, isLoading } = useQuery({ queryKey: ["admin-users"], queryFn: () => api.get("/auth/users") });
  const users: User[] = data?.data?.data || [];

  const { data: groupsData } = useQuery({ queryKey: ["admin-groups"], queryFn: () => api.get("/auth/groups") });
  const groups: Group[] = groupsData?.data?.data || [];

  const createMutation = useMutation({
    mutationFn: (user: Record<string, unknown>) => api.post("/auth/users", user),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin-users"] }); setShowCreate(false); },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, ...updates }: Record<string, unknown>) => api.patch(`/auth/users/${id}`, updates),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) => api.patch(`/auth/users/${id}`, { is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const resetMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) => api.post(`/auth/users/${id}/reset-password`, { new_password: password }),
    onSuccess: () => { setResetUserId(null); setNewPassword(""); },
  });

  const addGroupMutation = useMutation({
    mutationFn: ({ groupId, userId }: { groupId: string; userId: string }) => api.post(`/auth/groups/${groupId}/members`, { user_id: userId }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin-users"] }); queryClient.invalidateQueries({ queryKey: ["admin-groups"] }); },
  });

  const removeGroupMutation = useMutation({
    mutationFn: ({ groupId, userId }: { groupId: string; userId: string }) => api.delete(`/auth/groups/${groupId}/members/${userId}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin-users"] }); queryClient.invalidateQueries({ queryKey: ["admin-groups"] }); },
  });

  return (
    <div>
      <div className="mb-4 flex justify-end">
        <button onClick={() => setShowCreate(!showCreate)} className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">
          {showCreate ? "Cancel" : "Create User"}
        </button>
      </div>

      {showCreate && <CreateUserForm onSubmit={(u) => createMutation.mutate(u)} isPending={createMutation.isPending} error={createMutation.error} />}

      {resetUserId && (
        <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
          <h3 className="mb-2 text-sm font-semibold">Reset Password for {users.find((u) => u.id === resetUserId)?.username}</h3>
          <div className="flex gap-2">
            <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)}
              placeholder="New password (min 8 chars)" className="flex-1 rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            <button onClick={() => resetMutation.mutate({ id: resetUserId, password: newPassword })}
              disabled={newPassword.length < 8} className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white hover:bg-amber-700 disabled:opacity-50">Reset</button>
            <button onClick={() => setResetUserId(null)} className="rounded border border-gray-300 px-3 py-1.5 text-sm">Cancel</button>
          </div>
        </div>
      )}

      {isLoading ? <div className="text-gray-500">Loading...</div> : (
        <div className="space-y-2">
          {users.map((u) => (
            <div key={u.id} className="rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
              {/* User row */}
              <div className="flex items-center gap-4 px-4 py-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-100 text-sm font-bold text-brand-700 dark:bg-brand-900 dark:text-brand-300">
                  {u.username.charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-900 dark:text-white">{u.username}</span>
                    {u.first_name && <span className="text-sm text-gray-500">({u.first_name} {u.last_name})</span>}
                    <RoleBadge role={u.role} />
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${u.is_active ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                      {u.is_active ? "Active" : "Disabled"}
                    </span>
                    {u.auth_backend !== "local" && (
                      <span className="rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-medium text-purple-700">{u.auth_backend}</span>
                    )}
                  </div>
                  <div className="text-sm text-gray-500">{u.email || "No email"}</div>
                </div>

                {/* Group badges */}
                <div className="flex flex-wrap gap-1">
                  {u.groups?.map((g) => {
                    const group = groups.find((gr) => gr.name === g);
                    return (
                      <span key={g} className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900 dark:text-blue-300">
                        {g}
                        <button onClick={() => {
                          if (group) removeGroupMutation.mutate({ groupId: group.id, userId: u.id });
                        }} className="ml-0.5 text-blue-400 hover:text-blue-600">&times;</button>
                      </span>
                    );
                  })}
                  {(!u.groups || u.groups.length === 0) && (
                    <span className="text-xs text-gray-400">No groups</span>
                  )}
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1">
                  <button onClick={() => setEditingUser(editingUser === u.id ? null : u.id)}
                    className="rounded border border-gray-300 px-2 py-1 text-xs hover:bg-gray-100 dark:border-gray-600 dark:hover:bg-gray-700">
                    {editingUser === u.id ? "Close" : "Edit"}
                  </button>
                  <button onClick={() => setResetUserId(u.id)} className="rounded border border-gray-300 px-2 py-1 text-xs hover:bg-gray-100 dark:border-gray-600 dark:hover:bg-gray-700">
                    Reset PW
                  </button>
                  <button onClick={() => toggleMutation.mutate({ id: u.id, is_active: !u.is_active })}
                    className={`rounded border px-2 py-1 text-xs ${u.is_active ? "border-red-300 text-red-600 hover:bg-red-50" : "border-green-300 text-green-600 hover:bg-green-50"}`}>
                    {u.is_active ? "Disable" : "Enable"}
                  </button>
                </div>
              </div>

              {/* Expanded edit panel */}
              {editingUser === u.id && (
                <div className="border-t border-gray-200 bg-gray-50 px-4 py-3 dark:border-gray-700 dark:bg-gray-800/50">
                  <div className="grid grid-cols-4 gap-4">
                    {/* Role */}
                    <div>
                      <label className="mb-1 block text-xs font-medium text-gray-500">Role</label>
                      <select value={u.role}
                        onChange={(e) => updateMutation.mutate({ id: u.id, role: e.target.value })}
                        className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                        {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                      </select>
                    </div>

                    {/* Add to group */}
                    <div>
                      <label className="mb-1 block text-xs font-medium text-gray-500">Add to Group</label>
                      <select value=""
                        onChange={(e) => {
                          if (e.target.value) addGroupMutation.mutate({ groupId: e.target.value, userId: u.id });
                        }}
                        className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                        <option value="">Select group...</option>
                        {groups
                          .filter((g) => !u.groups?.includes(g.name))
                          .map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                      </select>
                    </div>

                    {/* Email */}
                    <div>
                      <label className="mb-1 block text-xs font-medium text-gray-500">Email</label>
                      <input type="text" defaultValue={u.email || ""}
                        onBlur={(e) => { if (e.target.value !== (u.email || "")) updateMutation.mutate({ id: u.id, email: e.target.value }); }}
                        className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                    </div>

                    {/* Name */}
                    <div>
                      <label className="mb-1 block text-xs font-medium text-gray-500">Display Name</label>
                      <div className="flex gap-1">
                        <input type="text" defaultValue={u.first_name} placeholder="First"
                          onBlur={(e) => { if (e.target.value !== u.first_name) updateMutation.mutate({ id: u.id, first_name: e.target.value }); }}
                          className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                        <input type="text" defaultValue={u.last_name} placeholder="Last"
                          onBlur={(e) => { if (e.target.value !== u.last_name) updateMutation.mutate({ id: u.id, last_name: e.target.value }); }}
                          className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
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
          { key: "username", label: "Username" },
          { key: "email", label: "Email" },
          { key: "password", label: "Password", type: "password" },
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

  const { data: usersData } = useQuery({ queryKey: ["admin-users"], queryFn: () => api.get("/auth/users") });
  const allUsers: User[] = usersData?.data?.data || [];

  const createMutation = useMutation({
    mutationFn: () => api.post("/auth/groups", { name: newGroupName, description: newGroupDesc }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin-groups"] }); setShowCreate(false); setNewGroupName(""); setNewGroupDesc(""); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/auth/groups/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin-groups"] }); setSelectedGroup(null); },
  });

  const addMemberMutation = useMutation({
    mutationFn: ({ groupId, userId }: { groupId: string; userId: string }) => api.post(`/auth/groups/${groupId}/members`, { user_id: userId }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin-group", selectedGroup] }); queryClient.invalidateQueries({ queryKey: ["admin-groups"] }); queryClient.invalidateQueries({ queryKey: ["admin-users"] }); },
  });

  const removeMemberMutation = useMutation({
    mutationFn: ({ groupId, userId }: { groupId: string; userId: string }) => api.delete(`/auth/groups/${groupId}/members/${userId}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin-group", selectedGroup] }); queryClient.invalidateQueries({ queryKey: ["admin-groups"] }); queryClient.invalidateQueries({ queryKey: ["admin-users"] }); },
  });

  const existingMemberIds = new Set(detail?.members?.map((m: { id: string }) => m.id) || []);

  return (
    <div className="grid grid-cols-3 gap-6">
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
              <div><div className="font-medium">{g.name}</div>{g.description && <div className="text-xs text-gray-500">{g.description}</div>}</div>
              <span className="text-xs text-gray-400">{g.member_count}</span>
            </button>
          ))}
          {groups.length === 0 && <div className="py-4 text-center text-sm text-gray-500">No groups. Create one to assign permissions.</div>}
        </div>
      </div>

      <div className="col-span-2">
        {detail ? (
          <div>
            <div className="mb-4 flex items-center justify-between">
              <div><h3 className="text-lg font-semibold">{detail.name}</h3>{detail.description && <p className="text-sm text-gray-500">{detail.description}</p>}</div>
              <button onClick={() => { if (confirm(`Delete group "${detail.name}"?`)) deleteMutation.mutate(detail.id); }}
                className="rounded border border-red-300 px-3 py-1 text-xs text-red-600 hover:bg-red-50">Delete Group</button>
            </div>

            <h4 className="mb-2 text-sm font-semibold text-gray-600">Members</h4>
            <div className="mb-4 rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
              {detail.members?.map((m: { id: string; username: string; role: string }) => (
                <div key={m.id} className="flex items-center justify-between border-b border-gray-100 px-3 py-2 last:border-0 dark:border-gray-700">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{m.username}</span>
                    <RoleBadge role={m.role} />
                  </div>
                  <button onClick={() => removeMemberMutation.mutate({ groupId: detail.id, userId: m.id })} className="text-xs text-red-500 hover:text-red-700">Remove</button>
                </div>
              ))}
              {(!detail.members || detail.members.length === 0) && <div className="px-3 py-3 text-center text-sm text-gray-500">No members yet</div>}
            </div>

            {/* Add member dropdown */}
            <select value=""
              onChange={(e) => { if (e.target.value) addMemberMutation.mutate({ groupId: detail.id, userId: e.target.value }); }}
              className="w-full rounded border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              <option value="">Add a user to this group...</option>
              {allUsers.filter((u) => !existingMemberIds.has(u.id)).map((u) => (
                <option key={u.id} value={u.id}>{u.username} ({u.role})</option>
              ))}
            </select>

            <div className="mt-4 rounded bg-blue-50 px-3 py-2 text-xs text-blue-700 dark:bg-blue-900/20 dark:text-blue-300">
              To assign per-model permissions to this group, go to the <strong>Permissions</strong> tab.
            </div>
          </div>
        ) : (
          <div className="flex h-64 items-center justify-center text-sm text-gray-500">Select a group to manage its members</div>
        )}
      </div>
    </div>
  );
}

// ─── Permissions Tab ────────────────────────────────────────────────────────

function PermissionsTab() {
  const queryClient = useQueryClient();
  const { categories, nodeTypes } = useSchemaStore();
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [showAddPerm, setShowAddPerm] = useState(false);
  const [permName, setPermName] = useState("");
  const [selectedTypes, setSelectedTypes] = useState<Set<string>>(new Set());
  const [permActions, setPermActions] = useState({ can_read: true, can_create: false, can_update: false, can_delete: false });
  const [jobPerms, setJobPerms] = useState({ can_execute_jobs: false, allowed_jobs: "" });

  const { data: groupsData } = useQuery({ queryKey: ["admin-groups"], queryFn: () => api.get("/auth/groups") });
  const groups: Group[] = groupsData?.data?.data || [];

  const { data: permData } = useQuery({
    queryKey: ["group-perms", selectedGroupId],
    queryFn: () => api.get(`/auth/groups/${selectedGroupId}/permissions`),
    enabled: !!selectedGroupId,
  });
  const perms: ObjPerm[] = permData?.data?.data || [];

  const createMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post(`/auth/groups/${selectedGroupId}/permissions`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["group-perms", selectedGroupId] });
      setShowAddPerm(false);
      setPermName("");
      setSelectedTypes(new Set());
      setPermActions({ can_read: true, can_create: false, can_update: false, can_delete: false });
      setJobPerms({ can_execute_jobs: false, allowed_jobs: "" });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/auth/permissions/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["group-perms", selectedGroupId] }),
  });

  const allNodeTypeNames = Object.keys(nodeTypes).sort();

  const toggleType = (name: string) => {
    const next = new Set(selectedTypes);
    if (next.has(name)) next.delete(name); else next.add(name);
    setSelectedTypes(next);
  };

  const toggleAllInCategory = (typeNames: string[]) => {
    const next = new Set(selectedTypes);
    const allSelected = typeNames.every((n) => next.has(n));
    typeNames.forEach((n) => { if (allSelected) next.delete(n); else next.add(n); });
    setSelectedTypes(next);
  };

  return (
    <div>
      {/* Group selector */}
      <div className="mb-4 flex items-center gap-4">
        <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Group:</label>
        <select value={selectedGroupId || ""}
          onChange={(e) => setSelectedGroupId(e.target.value || null)}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
          <option value="">Select a group to manage permissions...</option>
          {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
        </select>
        {groups.length === 0 && <span className="text-sm text-gray-500">Create a group first in the Groups tab</span>}
      </div>

      {selectedGroupId && (
        <>
          {/* Existing permissions */}
          {perms.length > 0 && (
            <div className="mb-6">
              <h3 className="mb-2 text-sm font-semibold text-gray-700 dark:text-gray-300">
                Current Permissions ({perms.length})
              </h3>
              <div className="space-y-2">
                {perms.map((p) => (
                  <div key={p.id} className="flex items-start justify-between rounded-lg border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-800">
                    <div>
                      <div className="font-medium text-gray-900 dark:text-white">{p.name}</div>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {p.can_read && <span className="rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-medium text-green-700">Read</span>}
                        {p.can_create && <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-700">Create</span>}
                        {p.can_update && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">Update</span>}
                        {p.can_delete && <span className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-700">Delete</span>}
                        {p.can_execute_jobs && <span className="rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-medium text-purple-700">Execute Jobs</span>}
                      </div>
                      <div className="mt-1 text-xs text-gray-500">
                        {p.object_types?.length > 0
                          ? <span>Models: {p.object_types.join(", ")}</span>
                          : <span className="italic">All models</span>}
                        {p.can_execute_jobs && p.allowed_jobs?.length > 0 && (
                          <span className="ml-2">| Jobs: {p.allowed_jobs.join(", ")}</span>
                        )}
                      </div>
                    </div>
                    <button onClick={() => deleteMutation.mutate(p.id)} className="rounded border border-red-300 px-2 py-1 text-xs text-red-600 hover:bg-red-50">Remove</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Add permission */}
          <div className="mb-2 flex justify-between">
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
              {showAddPerm ? "Add Permission" : ""}
            </h3>
            <button onClick={() => setShowAddPerm(!showAddPerm)}
              className="rounded bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700">
              {showAddPerm ? "Cancel" : "+ Add Permission"}
            </button>
          </div>

          {showAddPerm && (
            <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
              {/* Permission name */}
              <div className="mb-4">
                <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">Permission Name</label>
                <input type="text" value={permName} onChange={(e) => setPermName(e.target.value)}
                  placeholder="e.g., Circuit Read-Only, Full Network Admin"
                  className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
              </div>

              {/* CRUD actions */}
              <div className="mb-4">
                <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">Actions</label>
                <div className="flex gap-6">
                  {([
                    ["can_read", "Read", "View objects"],
                    ["can_create", "Create", "Create new objects"],
                    ["can_update", "Update", "Edit existing objects"],
                    ["can_delete", "Delete", "Delete objects"],
                  ] as const).map(([key, label, desc]) => (
                    <label key={key} className="flex items-start gap-2">
                      <input type="checkbox"
                        checked={permActions[key]}
                        onChange={(e) => setPermActions({ ...permActions, [key]: e.target.checked })}
                        className="mt-0.5" />
                      <div>
                        <div className="text-sm font-medium">{label}</div>
                        <div className="text-xs text-gray-500">{desc}</div>
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              {/* Model selector */}
              <div className="mb-4">
                <div className="mb-2 flex items-center justify-between">
                  <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
                    Models ({selectedTypes.size === 0 ? "All — leave empty for full access" : `${selectedTypes.size} selected`})
                  </label>
                  <div className="flex gap-2">
                    <button onClick={() => setSelectedTypes(new Set(allNodeTypeNames))}
                      className="text-xs text-brand-600 hover:text-brand-700">Select All</button>
                    <button onClick={() => setSelectedTypes(new Set())}
                      className="text-xs text-gray-500 hover:text-gray-700">Clear</button>
                  </div>
                </div>

                <div className="max-h-64 overflow-y-auto rounded border border-gray-200 dark:border-gray-700">
                  {categories.map((cat) => {
                    const catTypes = cat.node_types.filter((n) => nodeTypes[n]);
                    if (catTypes.length === 0) return null;
                    const allInCatSelected = catTypes.every((n) => selectedTypes.has(n));
                    const someInCatSelected = catTypes.some((n) => selectedTypes.has(n));

                    return (
                      <div key={cat.name} className="border-b border-gray-100 last:border-0 dark:border-gray-700">
                        {/* Category header */}
                        <label className="flex items-center gap-2 bg-gray-50 px-3 py-1.5 dark:bg-gray-800">
                          <input type="checkbox"
                            checked={allInCatSelected}
                            ref={(el) => { if (el) el.indeterminate = someInCatSelected && !allInCatSelected; }}
                            onChange={() => toggleAllInCategory(catTypes)} />
                          <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">{cat.name}</span>
                          <span className="text-[10px] text-gray-400">({catTypes.length})</span>
                        </label>
                        {/* Types in category */}
                        <div className="grid grid-cols-3 gap-0">
                          {catTypes.map((typeName) => {
                            const nt = nodeTypes[typeName];
                            return (
                              <label key={typeName} className="flex items-center gap-2 px-3 py-1 hover:bg-gray-50 dark:hover:bg-gray-700">
                                <input type="checkbox"
                                  checked={selectedTypes.has(typeName)}
                                  onChange={() => toggleType(typeName)} />
                                <span className="text-sm">{nt?.metadata.display_name || typeName}</span>
                              </label>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Job permissions */}
              <div className="mb-4 rounded border border-gray-200 p-3 dark:border-gray-700">
                <label className="flex items-center gap-2">
                  <input type="checkbox"
                    checked={jobPerms.can_execute_jobs}
                    onChange={(e) => setJobPerms({ ...jobPerms, can_execute_jobs: e.target.checked })} />
                  <div>
                    <span className="text-sm font-medium">Allow Job Execution</span>
                    <span className="ml-2 text-xs text-gray-500">Members can run automation jobs</span>
                  </div>
                </label>
                {jobPerms.can_execute_jobs && (
                  <div className="mt-2 pl-6">
                    <label className="mb-1 block text-xs font-medium text-gray-500">Allowed Jobs (comma-separated, empty = all jobs)</label>
                    <input type="text" value={jobPerms.allowed_jobs}
                      onChange={(e) => setJobPerms({ ...jobPerms, allowed_jobs: e.target.value })}
                      placeholder="iac_config_backup, iac_compliance_check"
                      className="w-full rounded border border-gray-300 px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                  </div>
                )}
              </div>

              {/* Submit */}
              <div className="flex justify-end">
                <button
                  onClick={() => createMutation.mutate({
                    name: permName,
                    ...permActions,
                    object_types: Array.from(selectedTypes),
                    ...jobPerms,
                    allowed_jobs: jobPerms.allowed_jobs ? jobPerms.allowed_jobs.split(",").map((s) => s.trim()) : [],
                  })}
                  disabled={!permName || createMutation.isPending}
                  className="rounded bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50">
                  {createMutation.isPending ? "Creating..." : "Create Permission"}
                </button>
              </div>
            </div>
          )}
        </>
      )}
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
      <div className="rounded-lg border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">LDAP / Active Directory</h3>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={!!ldapForm.enabled} onChange={(e) => setLdapForm({ ...ldapForm, enabled: e.target.checked })} /> Enabled
          </label>
        </div>
        <div className="grid grid-cols-2 gap-4">
          {[
            { key: "server_uri", label: "Server URI", placeholder: "ldap://dc.example.com:389" },
            { key: "bind_dn", label: "Bind DN", placeholder: "CN=svc-netgraphy,OU=Service Accounts,DC=example,DC=com" },
            { key: "bind_password", label: "Bind Password", type: "password" },
            { key: "user_search_base", label: "User Search Base", placeholder: "OU=Users,DC=example,DC=com" },
            { key: "user_search_filter", label: "User Search Filter", placeholder: "(sAMAccountName={username})" },
            { key: "group_search_base", label: "Group Search Base" },
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
          <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={ldapForm.auto_create_user !== false} onChange={(e) => setLdapForm({ ...ldapForm, auto_create_user: e.target.checked })} /> Auto-create users</label>
          <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={ldapForm.auto_sync_groups !== false} onChange={(e) => setLdapForm({ ...ldapForm, auto_sync_groups: e.target.checked })} /> Sync groups</label>
        </div>
        <div className="mt-4 flex justify-end">
          <button onClick={() => ldapMutation.mutate(ldapForm)} className="rounded bg-brand-600 px-4 py-1.5 text-sm text-white hover:bg-brand-700">
            {ldapMutation.isPending ? "Saving..." : "Save LDAP Config"}
          </button>
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">Single Sign-On (SAML / OIDC)</h3>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={!!ssoForm.enabled} onChange={(e) => setSsoForm({ ...ssoForm, enabled: e.target.checked })} /> Enabled
          </label>
        </div>
        <div className="mb-3">
          <label className="mb-1 block text-xs font-medium text-gray-500">Provider Type</label>
          <select value={String(ssoForm.provider_type || "none")} onChange={(e) => setSsoForm({ ...ssoForm, provider_type: e.target.value })}
            className="rounded border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
            <option value="none">None</option><option value="oidc">OIDC</option><option value="saml">SAML 2.0</option>
          </select>
        </div>
        <div className="grid grid-cols-2 gap-4">
          {(ssoForm.provider_type === "oidc" ? [
            { key: "oidc_discovery_url", label: "Discovery URL", placeholder: "https://idp.example.com/.well-known/openid-configuration" },
            { key: "oidc_client_id", label: "Client ID" },
            { key: "oidc_client_secret", label: "Client Secret", type: "password" },
          ] : ssoForm.provider_type === "saml" ? [
            { key: "saml_idp_metadata_url", label: "IdP Metadata URL" },
            { key: "saml_idp_sso_url", label: "IdP SSO URL" },
            { key: "saml_sp_entity_id", label: "SP Entity ID" },
          ] : []).map((f) => (
            <div key={f.key}>
              <label className="mb-1 block text-xs font-medium text-gray-500">{f.label}</label>
              <input type={f.type || "text"} value={String(ssoForm[f.key] || "")} placeholder={f.placeholder}
                onChange={(e) => setSsoForm({ ...ssoForm, [f.key]: e.target.value })}
                className="w-full rounded border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </div>
          ))}
          {ssoForm.provider_type && ssoForm.provider_type !== "none" && [
            { key: "group_claim", label: "Group Claim/Attribute", placeholder: "groups" },
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
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${colors[role] || colors.viewer}`}>{role}</span>;
}
