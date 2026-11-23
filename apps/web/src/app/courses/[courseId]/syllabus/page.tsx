import { Suspense } from "react";

import SyllabusInspector from "./inspector";

// The inspector reads localStorage and fetches at runtime, so this route
// cannot be prerendered under Cache Components / Partial Prefetching.
// Render it as a blocking dynamic route instead.
export const instant = false;

export default async function SyllabusInspectorPage({
  params,
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  return (
    <Suspense fallback={<div>Loading syllabus inspector...</div>}>
      <SyllabusInspector courseId={courseId} />
    </Suspense>
  );
}
