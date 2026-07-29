/**
 * Single authority for commands accepted by the Python JSON-lines backend.
 * Local Electron operations (dialogs and in-memory selection changes) are
 * deliberately absent: they never cross the backend transport boundary.
 */
export const BACKEND_COMMANDS = [
  "health",
  "app_info",
  "scan_collections",
  "convert_collection",
  "import_streamlabs",
  "automatic_import",
  "device_requirements",
  "device_candidates",
  "apply_device_choices",
  "obs_running",
  "activate_collection",
  "list_export_collections",
  "build_export_plan",
  "export_inventory",
  "confirm_export",
  "scan_resize_collections",
  "resize_source_choices",
  "resize_scene_choices",
  "preview_resize",
  "resize_collection",
  "undo_resize",
] as const;

export type BackendCommand = (typeof BACKEND_COMMANDS)[number];

const BACKEND_COMMAND_SET: ReadonlySet<string> = new Set(BACKEND_COMMANDS);

export function isBackendCommand(command: string): command is BackendCommand {
  return BACKEND_COMMAND_SET.has(command);
}
