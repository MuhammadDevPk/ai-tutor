import { Suspense } from "react";
import SessionReplayer from "./replayer";

export const instant = false;

export default async function SessionReplayPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  return (
    <Suspense fallback={<div className="p-8 text-sm text-zinc-500">Loading timeline replay...</div>}>
      <SessionReplayer sessionId={sessionId} />
    </Suspense>
  );
}
