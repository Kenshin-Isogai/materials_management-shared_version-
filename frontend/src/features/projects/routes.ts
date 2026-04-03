function appendEditProjectQuery(projectId: number): string {
  const params = new URLSearchParams({ edit: String(projectId) });
  return `/projects?${params.toString()}`;
}

export function projectEditorRoute(projectId: number | null | undefined): string {
  if (projectId == null || !Number.isFinite(projectId)) {
    return "/projects";
  }
  return appendEditProjectQuery(projectId);
}

export function projectBoardRoute(projectId: number | null | undefined): string {
  if (projectId == null || !Number.isFinite(projectId)) {
    return "/projects/board";
  }
  return `/projects/board/${projectId}`;
}
