import { Suspense } from "react";

import ClassroomAudioShell from "./classroom";

export const instant = false;

export default async function ClassroomPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  return (
    <Suspense fallback={<div className="p-8 text-sm text-zinc-500">Loading classroom session...</div>}>
      <ClassroomAudioShell sessionId={sessionId} />
    </Suspense>
  );
}
