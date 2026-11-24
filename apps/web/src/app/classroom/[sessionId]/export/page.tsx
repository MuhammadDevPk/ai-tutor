import { Suspense } from "react";
import StudyCheatSheet from "./cheatSheet";

export const instant = false;

export default async function StudyCheatSheetPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  return (
    <Suspense fallback={<div className="p-8 text-sm text-zinc-500">Loading study cheat sheet...</div>}>
      <StudyCheatSheet sessionId={sessionId} />
    </Suspense>
  );
}
