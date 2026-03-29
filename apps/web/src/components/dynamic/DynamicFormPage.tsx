/**
 * DynamicFormPage — auto-generated create/edit form for any node type.
 *
 * Fields are generated from the schema's attribute definitions.
 * Field types, validation, and widgets are determined by the attribute type
 * and UI metadata.
 */

import { useParams, useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSchemaStore } from "@/stores/schemaStore";
import { nodesApi } from "@/api/client";
import { FieldRenderer } from "./FieldRenderer";

export function DynamicFormPage() {
  const { nodeType, id } = useParams<{ nodeType: string; id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { getNodeType } = useSchemaStore();

  const isEdit = !!id;
  const typeDef = nodeType ? getNodeType(nodeType) : undefined;

  // Load existing data for edit mode
  const { data: existingData } = useQuery({
    queryKey: ["node", nodeType, id],
    queryFn: () => nodesApi.get(nodeType!, id!),
    enabled: isEdit,
  });

  const form = useForm({
    defaultValues: existingData?.data?.data || {},
  });

  const mutation = useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      isEdit
        ? nodesApi.update(nodeType!, id!, data)
        : nodesApi.create(nodeType!, data),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["nodes", nodeType] });
      const newId = isEdit ? id : result.data?.data?.id;
      navigate(`/objects/${nodeType}/${newId}`);
    },
  });

  if (!typeDef) {
    return <div className="text-red-500">Unknown node type: {nodeType}</div>;
  }

  const displayName = typeDef.metadata.display_name || nodeType;

  // Get form-visible attributes sorted by form_order
  const formAttributes = Object.entries(typeDef.attributes)
    .filter(([, attr]) => attr.ui.form_visible !== false && !attr.auto_set)
    .sort(
      (a, b) =>
        (a[1].ui.form_order ?? 999) - (b[1].ui.form_order ?? 999),
    );

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-6 text-2xl font-bold text-gray-900 dark:text-white">
        {isEdit ? `Edit ${displayName}` : `Create ${displayName}`}
      </h1>

      <form
        onSubmit={form.handleSubmit((data) => mutation.mutate(data))}
        className="space-y-6 rounded-lg border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800"
      >
        {formAttributes.map(([name, attr]) => (
          <div key={name}>
            <label
              htmlFor={name}
              className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              {attr.display_name || name}
              {attr.required && (
                <span className="ml-1 text-red-500">*</span>
              )}
            </label>
            <FieldRenderer
              value={form.watch(name)}
              attribute={attr}
              mode="edit"
              onChange={(value) => form.setValue(name, value)}
            />
            {form.formState.errors[name] && (
              <p className="mt-1 text-sm text-red-500">
                {String(form.formState.errors[name]?.message || "Required")}
              </p>
            )}
          </div>
        ))}

        <div className="flex justify-end gap-3 border-t border-gray-200 pt-4 dark:border-gray-700">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={mutation.isPending}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {mutation.isPending
              ? "Saving..."
              : isEdit
                ? "Save Changes"
                : `Create ${displayName}`}
          </button>
        </div>
      </form>
    </div>
  );
}
